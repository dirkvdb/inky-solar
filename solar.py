#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# from inky.auto import auto

import io, asyncio, os, pytz, json, argparse
from datetime import datetime
from datetime import date
from typing import Sequence, Tuple
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
    SQUARE_SANS_SERIF = 4
    BITTER_PRO_BLACK = 5
    BITTER_PRO_BOLD = 6


class HAlign(IntEnum):
    LEFT = 0
    RIGHT = 1
    CENTER = 2


class VAlign(IntEnum):
    TOP = 0
    BOTTOM = 1
    MIDDLE = 2


def average(lst):
    elements = len(lst)
    return 0 if elements == 0 else sum(lst) / len(lst)


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
    last_update_time: int = None
    forecast: bool
    timezone = None
    solar_values_minute = []
    solar_values_power = []
    solar_hourly_values = {}
    solar_hourly_prediction_values = []
    solar_predictions_minute = []
    solar_predictions_power = []
    minutes_between_updates: int

    def __init__(self, forecast: bool = False, minutes_between_updates: int = 1):
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
        self.minutes_between_updates = minutes_between_updates
        self.reset_hourly_values()

    def reset_hourly_values(self):
        self.solar_hourly_values = []
        for i in range(0, 24):
            self.solar_hourly_values.append([])
            self.solar_hourly_prediction_values.append(0)

    def append_solar_value(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute
        update_required = self.last_update_time == None or minute_in_the_day >= self.last_update_time + self.minutes_between_updates

        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.reset_hourly_values()
            self.solar_predictions_minute = []
            self.solar_predictions_power = []
            self.solar_values_minute = [minute_in_the_day]
            self.solar_values_power = [value]
        else:
            # append to todays timeseries
            self.solar_values_minute.append(minute_in_the_day)
            self.solar_values_power.append(value)

        self.solar_hourly_values[timestamp.hour].append(value)
        if update_required:
            self.update_solar_prediction_if_needed()
            self.last_update_time = minute_in_the_day

        self.last_solar_time = minute_in_the_day
        return update_required

    def append_solar_value_normalized(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute
        update_required = minute_in_the_day > self.last_solar_time

        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.reset_hourly_values()
            self.solar_predictions_minute = []
            self.solar_predictions_power = []
            self.solar_values_minute = [minute_in_the_day / MINUTES_IN_A_DAY]
            self.solar_values_power = [value / MAX_SOLAR_POWER]
        else:
            # append to todays timeseries
            self.solar_values_minute.append(minute_in_the_day / MINUTES_IN_A_DAY)
            self.solar_values_power.append(value / MAX_SOLAR_POWER)

        self.solar_hourly_values[timestamp.hour].append(value)
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
                    if timestamp.minute == 0:
                        self.solar_hourly_prediction_values[timestamp.hour] = est / MAX_SOLAR_POWER
                        print(f"Prediction for {timestamp.date()} {timestamp.hour}:{timestamp.minute} {est}Wh")
        except Exception as e:
            print(f"Failed to obtain solar predictions: {e}")


def format_watts(val: float):
    if val < 1000:
        return "{:.0f}W".format(val)
    else:
        return "{:.1f}kW".format(val / 1000.0)


def format_watt_hours(val: float):
    if val < 1000:
        return "{:.0f}Wh".format(val)
    else:
        return "{:.1f}kWh".format(val / 1000.0)


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
    graph_bars_actual = None
    graph_bars_estimate = None
    table = False
    table_row_height = 40

    def __init__(self, width: int, height: int, simulate: bool = False, bar_chart: bool = False, table: bool = False, color: bool = False):
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

        self.table = table
        self.img = Image.new("P", (self.width, self.height), Color.WHITE)
        self.draw = ImageDraw.Draw(self.img)

        if color:
            self.img.putpalette(ylw_inky_palette)
        else:
            self.img.putpalette(bw_inky_palette)

        bbox = self.graph_bbox()
        dpi = 80
        self.figure = plt.figure(figsize=[bbox.width / dpi, bbox.height / dpi], dpi=dpi, frameon=False)

        if bar_chart:
            x = 0
            bar_width = 1 / 24
            self.graph_bars_actual = []
            self.graph_bars_estimate = []

            fc_estimate = "yellow" if color else "none"

            for _ in range(0, 24):
                bar = matplotlib.patches.Rectangle((x, 0), bar_width, 0, fc="black", ec="none")
                self.graph_bars_actual.append(bar)

                bar = matplotlib.patches.Rectangle((x, 0), bar_width, 0, fc=fc_estimate, ec="black", lw=0.1)
                self.graph_bars_estimate.append(bar)
                x += bar_width

            for bar in self.graph_bars_estimate:
                self.figure.add_artist(bar)

            for bar in self.graph_bars_actual:
                self.figure.add_artist(bar)
        else:
            # line chart
            self.graph_line_actual = matplotlib.lines.Line2D([], [], lw=3, ls="-", snap=True)
            self.figure.add_artist(self.graph_line_actual)

            self.graph_line_estimate = matplotlib.lines.Line2D([], [], lw=2, linestyle=(0, (5, 6)), snap=True)
            self.figure.add_artist(self.graph_line_estimate)

    def draw_graph(self, data: DisplayData):
        buf = io.BytesIO()
        bbox = self.graph_bbox()

        if self.graph_line_actual:
            self.graph_line_actual.set_xdata(data.solar_values_minute)
            self.graph_line_actual.set_ydata(data.solar_values_power)

        if self.graph_bars_actual:
            for i in range(0, 24):
                values = data.solar_hourly_values[i]
                self.graph_bars_actual[i].set_height(average(values) / MAX_SOLAR_POWER)

        if self.graph_bars_estimate:
            for i in range(0, 24):
                self.graph_bars_estimate[i].set_height(data.solar_hourly_prediction_values[i])

        if self.graph_line_estimate:
            self.graph_line_estimate.set_xdata(data.solar_predictions_minute)
            self.graph_line_estimate.set_ydata(data.solar_predictions_power)

        self.figure.savefig(buf, format="png")
        plot_image = Image.open(buf).convert("RGB").quantize(palette=self.img)
        self.img.paste(plot_image, bbox.topleft)

        self.draw.rectangle((bbox.topleft, bbox.bottomright), outline=Color.BLACK, width=1)

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
            elif fond_code == Font.SQUARE_SANS_SERIF:
                self.fonts[font_def] = ImageFont.truetype("fonts/square_sans_serif_7.ttf", size=font_def[1])
            elif fond_code == Font.BITTER_PRO_BLACK:
                self.fonts[font_def] = ImageFont.truetype("fonts/BitterPro-Black.ttf", size=font_def[1])
            elif fond_code == Font.BITTER_PRO_BOLD:
                self.fonts[font_def] = ImageFont.truetype("fonts/BitterPro-Bold.ttf", size=font_def[1])
            else:
                raise RuntimeError("Invalid font")

        return self.fonts[font_def]

    def render(self, disp_data: DisplayData):
        # clear the canvas
        self.draw.rectangle((0, 0, WIDTH, HEIGHT), fill=Color.WHITE)

        if self.table:
            self.render_table(disp_data)
        else:
            self.render_icons(disp_data)
        self.draw_graph(disp_data)
        self.show()

    def render_icons(self, disp_data: DisplayData):
        high_export = disp_data.export_current > 2000

        self.draw_info_icon(0, format_watts(disp_data.import_current), format_watts(disp_data.import_today), "plug")
        self.draw_info_icon(1, format_watts(disp_data.solar_current), format_watts(disp_data.solar_today), "sun")
        self.draw_info_icon(2, format_watts(disp_data.export_current), format_watts(disp_data.export_today), "solar-panel", colored_background=high_export)

    def render_table(self, disp_data: DisplayData):
        high_export = disp_data.export_current > 2000

        self.draw_table_row(0, ["Import", format_watts(disp_data.import_current), format_watt_hours(disp_data.import_today)], "plug")
        self.draw_table_row(1, ["Zon", format_watts(disp_data.solar_current), format_watt_hours(disp_data.solar_today)], "sun")
        self.draw_table_row(
            2, ["Export", format_watts(disp_data.export_current), format_watt_hours(disp_data.export_today)], "solar-panel", colored_background=high_export
        )

    def info_icon_bbox(self, index: int):
        icon_space_width = (self.width - (self.margin_hor * 2) - (self.icon_columns - 1) * self.padding) / self.icon_columns
        top_left = (self.margin_hor + ((icon_space_width + self.padding) * index), self.margin_ver)

        return Rect(top_left[0], top_left[1], icon_space_width, icon_space_width)

    def table_row_bbox(self, index: int) -> Rect:
        table_width = self.width - (self.margin_hor * 2)
        top_left = (self.margin_hor, self.margin_ver + (index * self.table_row_height))

        return Rect(top_left[0], top_left[1], table_width, self.table_row_height)

    def table_bbox(self):
        row_count = 3
        row_bbox = self.table_row_bbox(0)
        row_bbox.height = row_bbox.height * row_count
        return row_bbox

    def graph_bbox(self):
        top_bbox = None
        if self.table:
            top_bbox = self.table_bbox()
        else:
            top_bbox = self.info_icon_bbox(0)

        graph_bbox = top_bbox.copy()
        graph_bbox.move(0, top_bbox.height)
        graph_bbox.size = (self.width - (self.margin_hor * 2), self.height - (self.margin_ver * 2) - top_bbox.height)

        return graph_bbox

    def draw_table_row(self, index: int, texts: Sequence[str], icon: str, colored_background: bool = False):
        col_count = len(texts)
        bbox = self.table_row_bbox(index)
        fill_color = Color.COLOR if colored_background else Color.WHITE
        self.draw.rectangle((bbox.topleft, bbox.bottomright), fill=fill_color, outline=Color.BLACK)

        text_rect = Rect(bbox.left, bbox.top, bbox.width / col_count, bbox.height)
        self.draw.rectangle((text_rect.topleft, text_rect.bottomright), fill=Color.BLACK)
        self.draw_text(
            text_rect,
            texts[0],
            Color.WHITE,
            (Font.BITTER_PRO_BLACK, 22),
            HAlign.CENTER,
            VAlign.MIDDLE,
        )
        text_rect.move(text_rect.width, 0)

        for txt in texts[1:]:
            self.draw_text(
                text_rect,
                txt,
                Color.BLACK,
                (Font.BITTER_PRO_BLACK, 22),
                HAlign.CENTER,
                VAlign.MIDDLE,
            )
            text_rect.move(text_rect.width, 0)

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
            (Font.SQUARE_SANS_SERIF, 20),
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
            (Font.SQUARE_SANS_SERIF, 20),
            HAlign.CENTER,
            VAlign.MIDDLE,
        )

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
    parser.add_argument("--color", "-c", action=argparse.BooleanOptionalAction, help="Use the three color palette instead of black and white")
    parser.add_argument("--table", "-t", action=argparse.BooleanOptionalAction, help="Show table instead of icons")
    args = parser.parse_args()

    img = DashImage(WIDTH, HEIGHT, simulate=args.simulate, bar_chart=True, table=args.table, color=args.color)
    update_rate = 5 if args.color else 1
    disp_data = DisplayData(forecast=args.forecast, minutes_between_updates=update_rate)

    if args.simulate:
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        # generate some data for testing
        import random

        for h in range(0, 12):
            for m in range(0, 60):
                disp_data.append_solar_value_normalized(datetime(2023, 2, 1, hour=h, minute=m), 2000.0 + (random.random() * 3000))
        img.render(disp_data)
    else:
        subscribe_to_data(args.mqtt_addr, args.mqtt_port, (disp_data, img))
        input("Press Enter to continue.\n")
