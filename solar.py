#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# from inky.auto import auto

import json
import io
import argparse
from datetime import datetime
import numpy as np
from typing import Tuple
import pytz
from dataclasses import dataclass
from enum import IntEnum
from pyrect import Rect
from PIL import Image, ImageFont, ImageDraw
from font_source_serif_pro import SourceSerifProSemibold
from font_source_sans_pro import SourceSansProSemibold
from font_font_awesome import FontAwesome5FreeSolid
import fontawesome as fa
import paho.mqtt.client as mqtt

try:
    from pandas import DataFrame
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    graphing_support = True
except:
    graphing_support = False
    print("graphs not available")


TOPIC_SOLAR = "pvpanelendak/PUB/CH1"
TOPIC_NETTO = "244cab25438c/PUB/CH0"
TOPIC_IMPORT = "244cab25438c/PUB/CH2"
TOPIC_EXPORT = "244cab25438c/PUB/CH3"
MINUTES_IN_A_DAY = 24 * 60

FONT_SIZE = 40
ICON_FONT_SIZE = 32

# white_color = inky_display.WHITE
# black_color = inky_display.BLACK
# red_color = inky_display.RED


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


class DisplayData:
    netto_current: float
    export_current: float
    export_today: float
    import_current: float
    import_today: float
    solar_current: float
    solar_today: float
    last_solar_time: int
    solar_values = None
    timezone = None

    def __init__(self):
        self.netto_current = 0.0
        self.export_current = 0.0
        self.export_today = 0.0
        self.import_current = 0.0
        self.import_today = 0.0
        self.solar_current = 0.0
        self.solar_today = 0.0
        if graphing_support:
            self.solar_values = DataFrame(columns=["time", "value"])
        self.last_solar_time = 0
        self.timezone = pytz.timezone("Europe/Brussels")

    def append_solar_value(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute
        update_required = minute_in_the_day > self.last_solar_time
        
        if not graphing_support:
            return update_required

        df = DataFrame.from_dict({"time": [minute_in_the_day], "value": [value]})
        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.solar_values = df
        else:
            # append to todays timeseries
            self.solar_values = pd.concat([self.solar_values, df])

        self.last_solar_time = minute_in_the_day
        return update_required


def format_watts(val: float):
    if val < 1000:
        return f"{val}W"
    else:
        return "{:.1f}kW".format(val / 1000.0)


# Set up the correct display and scaling factors

# inky_display = auto(ask_user=True, verbose=True)
# inky_display.set_border(inky_display.WHITE)
# inky_display.set_rotation(180)

# WIDTH = inky_display.width
# HEIGHT = inky_display.height
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

    def __init__(self, width: int, height: int, simulate: bool):
        if not simulate:
            import inky
            self.display = inky.InkyWHAT('black')
            self.display.h_flip = True
            self.display.v_flip = True
            self.width = self.display.WIDTH
            self.height = self.display.HEIGHT
        else:
            self.width = width
            self.height = height

        self.img = Image.new("P", (self.width, self.height), Color.WHITE)
        self.draw = ImageDraw.Draw(self.img)

        if simulate:
            self.img.putpalette(ylw_inky_palette)

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

        if graphing_support:
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
        bbox = self.graph_bbox()
        # data = DataFrame.from_records(data.todays_values)
        fig = go.Figure()
        # fig = px.line(data, x=x, y=y, width=bbox.width, height=bbox.height)
        fig = px.line(data.solar_values, x="time", y="value")
        fig.update_layout(showlegend=False)
        fig.update_xaxes(visible=False, showticklabels=False, range=[0, MINUTES_IN_A_DAY])
        fig.update_yaxes(visible=False, showticklabels=False, range=[0, 8000])
        fig.update_layout(showlegend=False, plot_bgcolor="white", autosize=False, width=bbox.width, height=bbox.height, margin=dict(t=0, l=0, b=0, r=0))
        # fig.show()

        # self.draw.rectangle((bbox.topleft, bbox.bottomright), fill=Color.COLOR)
        # graph_img = Image.open(io.BytesIO(fig.to_image(format="png"))).convert("P", palette=bw_inky_palette, dither=Image.Dither.FLOYDSTEINBERG)
        graph_img = Image.open(io.BytesIO(fig.to_image(format="png"))).convert("RGB")
        img_data = np.asarray(graph_img)
        paletted_data = np.ndarray((bbox.height, bbox.width), dtype=np.uint8)
        paletted_data.fill(Color.WHITE)

        mask = (img_data != 255).all(axis=-1)
        paletted_data[mask] = Color.BLACK
        # paletted_data[mask] = Color.BLACK

        graph_img = Image.fromarray(paletted_data, mode="P")
        graph_img.putpalette(ylw_inky_palette)
        self.img.paste(graph_img, bbox.topleft)

    def show(self):
        if self.display:
            print("Update")
            self.display.set_image(self.img)
            self.display.show()
        else:
            self.img.convert("RGB").show()

    def draw_text(self, bbox: Rect, text: str, color: Color, font: Tuple[Font, int], h_align=HAlign.LEFT, v_align=VAlign.BOTTOM):
        """
        Draws text and returns its size
        """
        # Calculate size
        # size = self.draw.textsize(str(text), font=self.fonts[int(font)])
        # size = self.draw.textlength(str(text), font=self.fonts[int(font)])
        # (left, top, right, bottom) = self.draw.textbbox(str(text), font=self.__load_font(font))
        # size = (right - left, bottom - top)
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


# Display the completed canvas on Inky wHAT

# inky_display.set_image(img)
# inky_display.show()


def on_message(_, userdata: Tuple[DisplayData, DashImage], message):
    disp_data, image = userdata
    data = json.loads(message.payload)

    if message.topic == TOPIC_SOLAR:
        print("Solar data")
        disp_data.solar_current = data["P"]
        disp_data.solar_today = data["DC"]
        if disp_data.append_solar_value(datetime.now(disp_data.timezone), disp_data.solar_current):
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
    args = parser.parse_args()

    disp_data = DisplayData()
    img = DashImage(WIDTH, HEIGHT, simulate=args.simulate)
    subscribe_to_data(args.mqtt_addr, args.mqtt_port, (disp_data, img))

    # img.render(disp_data)
    # img.show()
    input("Press Enter to continue.\n")
