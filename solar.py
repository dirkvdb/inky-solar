#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# from inky.auto import auto

import io, asyncio, os, pytz, json, argparse
from datetime import datetime
from datetime import date
from typing import Tuple
from enum import IntEnum
from pyrect import Rect
from PIL import Image, ImageFont, ImageDraw
from font_font_awesome import FontAwesome5FreeSolid
from forecast_solar import ForecastSolar
import fontawesome as fa
import paho.mqtt.client as mqtt
import matplotlib
from matplotlib import pyplot as plt


TOPIC_SOLAR = "pvpanelendak/PUB/CH1"
TOPIC_NETTO = "244cab25438c/PUB/CH0"
TOPIC_IMPORT = "244cab25438c/PUB/CH2"
TOPIC_EXPORT = "244cab25438c/PUB/CH3"
MINUTES_IN_A_DAY = 24 * 60
MAX_SOLAR_POWER = 8000

FONT_SIZE = 40
ICON_FONT_SIZE = 32


class Color(IntEnum):
    WHITE = 0
    BLACK = 1
    COLOR = 2


class Font(IntEnum):
    FONT_AWESOME = 0
    ROBOTO_BOLD = 1
    ROBOTO_LIGHT = 2
    ROBOTO_REGULAR = 3


class HAlign(IntEnum):
    LEFT = 0
    RIGHT = 1
    CENTER = 2


class VAlign(IntEnum):
    TOP = 0
    BOTTOM = 1
    MIDDLE = 2


async def get_solar_forecast():
    async with ForecastSolar(
        latitude=51.23747747561697,
        longitude=5.287941297968982,
        declination=45,
        azimuth=135,
        kwp=8.0,
        damping_morning=0.2,
        damping_evening=0,
    ) as forecast:
        return await forecast.estimate()


class DisplayData:
    netto_current: float
    export_current: float
    export_today: float
    import_current: float
    import_today: float
    solar_current: float
    solar_today: float
    last_solar_time: int
    forecast: bool
    timezone = None
    solar_values_minute = []
    solar_values_power = []
    solar_predictions_minute = []
    solar_predictions_power = []

    def __init__(self, forecast: bool = False):
        self.netto_current = 0.0
        self.export_current = 0.0
        self.export_today = 0.0
        self.import_current = 0.0
        self.import_today = 0.0
        self.solar_current = 0.0
        self.solar_today = 0.0
        self.last_solar_time = MINUTES_IN_A_DAY + 1
        self.timezone = pytz.timezone("Europe/Brussels")
        self.forecast = forecast

    def append_solar_value(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute
        update_required = minute_in_the_day > self.last_solar_time

        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.solar_predictions_minute = []
            self.solar_predictions_power = []
            self.solar_values_minute = [minute_in_the_day]
            self.solar_values_power = [value]
        else:
            # append to todays timeseries
            self.solar_values_minute.append(minute_in_the_day)
            self.solar_values_power.append(value)

        self.last_solar_time = minute_in_the_day
        self.update_solar_prediction_if_needed()
        return update_required

    def append_solar_value_normalized(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute
        update_required = minute_in_the_day > self.last_solar_time

        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.solar_values_minute = [minute_in_the_day / MINUTES_IN_A_DAY]
            self.solar_values_power = [value / MAX_SOLAR_POWER]
        else:
            # append to todays timeseries
            self.solar_values_minute.append(minute_in_the_day / MINUTES_IN_A_DAY)
            self.solar_values_power.append(value / MAX_SOLAR_POWER)

        self.last_solar_time = minute_in_the_day
        self.update_solar_prediction_if_needed()
        return update_required

    def update_solar_prediction_if_needed(self):
        if (not self.forecast) or len(self.solar_predictions_minute) > 0:
            # predictions already obtained for the current day
            return

        try:
            print("Update solar predictions")
            estimations = asyncio.run(get_solar_forecast())
            for timestamp, est in estimations.watts.items():
                if timestamp.date() == date.today():
                    minute_in_the_day = (timestamp.hour * 60) + 30  # put the points on the half hour marks
                    self.solar_predictions_minute.append(minute_in_the_day / MINUTES_IN_A_DAY)
                    self.solar_predictions_power.append(est / MAX_SOLAR_POWER)
                    print(f"Prediction for {timestamp.date()} {est}Wh")
        except Exception as e:
            print("Failed to obtain solar predictions: {e}")


def format_watts(val: float):
    if val < 1000:
        return f"{val}W"
    else:
        return "{:.1f}kW".format(val / 1000.0)


WIDTH = 400
HEIGHT = 300

# Create a new canvas to draw on
ylw_inky_palette = [
    255,
    255,
    255,  # 0 = white
    0,
    0,
    0,  # 1 = black
    223,
    204,
    16,
]  # index 2 is yellow

bw_inky_palette = [
    255,
    255,
    255,  # 0 = white
    0,
    0,
    0,  # 1 = black
]  # index 2 is yellow


class DashImage:
    width = 0
    height = 0
    margin_ver = 10
    margin_hor = margin_ver
    padding = 7  # padding between the internal elements
    icon_columns = 3  # number of info icons
    img = None
    draw = None
    fonts = {}
    display = None
    palette = None
    figure = None
    graph_line_actual = None
    graph_line_estimate = None

    def __init__(self, width: int, height: int, simulate: bool):
        if not simulate:
            from inky import InkyWHAT

            self.display = InkyWHAT("black")
            self.display.h_flip = True
            self.display.v_flip = True
            self.width = self.display.WIDTH
            self.height = self.display.HEIGHT
        else:
            self.width = width
            self.height = height

        self.img = Image.new("P", (self.width, self.height), Color.WHITE)
        self.img.putpalette(bw_inky_palette)
        self.draw = ImageDraw.Draw(self.img)

        bbox = self.graph_bbox()
        dpi = 80
        self.figure = plt.figure(figsize=[bbox.width / dpi, bbox.height / dpi], dpi=dpi, frameon=False)
        self.graph_line_actual = matplotlib.lines.Line2D([], [], lw=3, ls="-", snap=True)
        self.graph_line_estimate = matplotlib.lines.Line2D([], [], lw=1, linestyle=(0, (5, 10)), snap=True)
        self.figure.add_artist(self.graph_line_actual)
        self.figure.add_artist(self.graph_line_estimate)

    def __load_font(self, font_def: Tuple[Font, int]):
        if font_def not in self.fonts:
            fond_code = font_def[0]
            if fond_code == Font.ROBOTO_BOLD:
                self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-Bold.ttf", size=font_def[1])
            elif fond_code == Font.ROBOTO_LIGHT:
                self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-Light.ttf", size=font_def[1])
            elif fond_code == Font.ROBOTO_REGULAR:
                self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-Regular.ttf", size=font_def[1])
            elif fond_code == Font.FONT_AWESOME:
                self.fonts[font_def] = ImageFont.truetype(FontAwesome5FreeSolid, size=font_def[1])
            else:
                raise RuntimeError("Invalid font")

        return self.fonts[font_def]

    def render(self, disp_data: DisplayData):
        # clear the canvas
        self.draw.rectangle((0, 0, WIDTH, HEIGHT), fill=Color.WHITE)

        high_export = disp_data.export_current > 2000

        self.draw_info_icon(0, format_watts(disp_data.import_current), format_watts(disp_data.import_today), "plug")
        self.draw_info_icon(1, format_watts(disp_data.solar_current), format_watts(disp_data.solar_today), "sun")
        self.draw_info_icon(2, format_watts(disp_data.export_current), format_watts(disp_data.export_today), "solar-panel", colored_background=high_export)
        self.draw_graph(disp_data)

        self.show()

    def info_icon_bbox(self, index: int):
        icon_space_width = (self.width - (self.margin_hor * 2) - (self.icon_columns - 1) * self.padding) / self.icon_columns
        top_left = (self.margin_hor + ((icon_space_width + self.padding) * index), self.margin_ver)

        return Rect(top_left[0], top_left[1], icon_space_width, icon_space_width)

    def graph_bbox(self):
        icon_bbox = self.info_icon_bbox(0)

        graph_bbox = icon_bbox.copy()
        graph_bbox.move(0, icon_bbox.height)
        graph_bbox.size = (self.width - (self.margin_hor * 2), self.height - (self.margin_ver * 2) - icon_bbox.height)

        return graph_bbox

    def draw_info_icon(self, index: int, text_top: str, text_bottom: str, icon: str, colored_background: bool = False):
        bbox = self.info_icon_bbox(index)

        text_height = bbox.height / 4
        icon_height = bbox.height / 2

        if colored_background:
            self.draw.rectangle((bbox.topleft, bbox.bottomright), fill=Color.COLOR)

        text_rect = Rect(bbox.left, bbox.top, bbox.width, text_height)
        self.draw_text(
            text_rect,
            text_top,
            Color.BLACK,
            (Font.ROBOTO_BOLD, 20),
            HAlign.CENTER,
            VAlign.MIDDLE,
        )

        icon_rect = Rect(bbox.left, text_rect.bottom, bbox.width, icon_height)
        self.draw_icon(icon_rect, icon, Color.BLACK, 50)

        text_rect.move(0, text_rect.height + icon_rect.height)
        self.draw_text(
            text_rect,
            text_bottom,
            Color.BLACK,
            (Font.ROBOTO_BOLD, 20),
            HAlign.CENTER,
            VAlign.MIDDLE,
        )

    def draw_graph(self, data: DisplayData):
        buf = io.BytesIO()
        bbox = self.graph_bbox()

        self.graph_line_actual.set_xdata(data.solar_values_minute)
        self.graph_line_actual.set_ydata(data.solar_values_power)

        self.graph_line_estimate.set_xdata(data.solar_predictions_minute)
        self.graph_line_estimate.set_ydata(data.solar_predictions_power)

        self.figure.savefig(buf, format="png")
        plot_image = Image.open(buf).convert("P", palette=bw_inky_palette)
        self.img.paste(plot_image, bbox.topleft)

        self.draw.rectangle((bbox.topleft, bbox.bottomright), outline=Color.BLACK, width=1)

    def show(self):
        print("[{}] Update".format(datetime.now().strftime("%H:%M:%S")))
        if self.display:
            self.display.set_image(self.img)
            self.display.show()
        else:
            self.img.convert("RGB").show()

    def draw_text(self, bbox: Rect, text: str, color: Color, font: Tuple[Font, int], h_align: HAlign = HAlign.LEFT, v_align: VAlign = VAlign.BOTTOM):
        """
        Draws text and returns its size
        """
        # Calculate size
        size = self.size_text(text, font)

        halign_code = ["l", "r", "m"]
        valign_code = ["t", "b", "m"]

        # Draw
        anchor = f"{halign_code[int(h_align)]}{valign_code[int(v_align)]}"
        x, y = bbox.topleft
        if h_align == HAlign.LEFT:
            x = bbox.left
        elif h_align == HAlign.CENTER:
            x = bbox.centerx
        elif h_align == HAlign.RIGHT:
            x = bbox.right

        if v_align == VAlign.TOP:
            y = bbox.top
        elif v_align == VAlign.MIDDLE:
            y = bbox.centery
        elif v_align == VAlign.BOTTOM:
            y = bbox.bottom

        self.draw.text((x, y), str(text), fill=color, font=self.__load_font(font), anchor=anchor)
        return size

    def draw_icon(self, pos: Rect, name: str, color: Color, size: int):
        self.draw_text(pos, fa.icons[name], color, (Font.FONT_AWESOME, size), h_align=HAlign.CENTER, v_align=VAlign.MIDDLE)

    def size_text(self, text: str, font: Font):
        """
        Returns text size
        """
        # Calculate size
        (left, top, right, bottom) = self.draw.textbbox((0, 0), str(text), font=self.__load_font(font))
        return Rect(left, top, right - left, bottom - top)


def on_message(_, userdata: Tuple[DisplayData, DashImage], message):
    disp_data, image = userdata
    data = json.loads(message.payload)

    if message.topic == TOPIC_SOLAR:
        print("[{}] Solar data".format(datetime.now().strftime("%H:%M:%S")))
        disp_data.solar_current = data["P"]
        disp_data.solar_today = data["DC"]
        if disp_data.append_solar_value_normalized(datetime.now(disp_data.timezone), disp_data.solar_current):
            # solar is broadcast every minute, use this as the update interval
            image.render(disp_data)

    elif message.topic == TOPIC_NETTO:
        imp = float(data["PI"])
        exp = float(data["PE"])
        disp_data.netto_current = imp - exp
        disp_data.import_current = imp
        disp_data.export_current = exp
    elif message.topic == TOPIC_IMPORT:
        disp_data.import_today = float(data["DC"])
    elif message.topic == TOPIC_EXPORT:
        disp_data.export_today = float(data["DC"])


def subscribe_to_data(mqtt_ip: str, mqtt_port: int, user_data: Tuple[DisplayData, DashImage]):
    client = mqtt.Client("statusdisp", protocol=mqtt.MQTTv5)
    client.on_message = on_message
    client.user_data_set(user_data)
    client.connect(mqtt_ip, mqtt_port, keepalive=60)
    client.loop_start()
    (result, _) = client.subscribe([(TOPIC_SOLAR, 0), (TOPIC_NETTO, 0), (TOPIC_IMPORT, 0), (TOPIC_EXPORT, 0)], qos=2)

    if result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError("Failed to subscribe to mqtt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mqtt-addr", "-m", type=str, required=True, help="IP address of the mqtt server")
    parser.add_argument("--mqtt-port", "-p", type=int, required=False, default=1883, help="IP address of the mqtt server")
    parser.add_argument("--simulate", "-s", action=argparse.BooleanOptionalAction, help="Support running without inky display")
    parser.add_argument("--forecast", "-f", action=argparse.BooleanOptionalAction, help="Display the solar forecast in the graph")
    args = parser.parse_args()

    img = DashImage(WIDTH, HEIGHT, simulate=args.simulate)
    disp_data = DisplayData(forecast=args.forecast)

    if args.simulate:
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        # generate some data for testing
        import random

        for h in range(0, 24):
            for m in range(0, 60):
                disp_data.append_solar_value_normalized(datetime(2023, 2, 1, hour=h, minute=m), 2000.0 + (random.random() * 3000))
        img.render(disp_data)
    else:
        subscribe_to_data(args.mqtt_addr, args.mqtt_port, (disp_data, img))
        input("Press Enter to continue.\n")
