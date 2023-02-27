#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# from inky.auto import auto

import json
import io
from datetime import datetime
import numpy as np
from typing import Tuple
from pandas import DataFrame
import pandas as pd
import pytz
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from PIL import Image, ImageFont, ImageDraw
from font_source_serif_pro import SourceSerifProSemibold
from font_source_sans_pro import SourceSansProSemibold
from font_font_awesome import FontAwesome5FreeSolid
from pyrect import Rect
import fontawesome as fa
import plotly.express as px
import plotly.graph_objects as go

import paho.mqtt.client as mqtt

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


class HAlign(StrEnum):
    LEFT = "l"
    RIGHT = "r"
    CENTER = "m"


class VAlign(StrEnum):
    TOP = "t"
    BOTTOM = "b"
    MIDDLE = "m"


class DisplayData:
    netto_current: float
    export_current: float
    export_today: float
    import_current: float
    import_today: float
    solar_current: float
    solar_today: float
    solar_values: DataFrame
    last_solar_time: int
    timezone = None

    def __init__(self):
        self.netto_current = 0.0
        self.export_current = 0.0
        self.export_today = 0.0
        self.import_current = 0.0
        self.import_today = 0.0
        self.solar_current = 0.0
        self.solar_today = 0.0
        self.solar_values = DataFrame(columns=["time", "value"])
        self.last_solar_time = 0
        self.timezone = pytz.timezone("Europe/Brussels")

    def append_solar_value(self, timestamp: datetime, value: float):
        minute_in_the_day = (timestamp.hour * 60) + timestamp.minute

        df = DataFrame.from_dict({"time": [minute_in_the_day], "value": [value]})
        if minute_in_the_day < self.last_solar_time:
            # new day started, reset the timeseries to the new value
            self.solar_values = df
        else:
            # append to todays timeseries
            self.solar_values = pd.concat([self.solar_values, df])

        self.last_solar_time = minute_in_the_day


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

    def __init__(self, width: int, height: int, palette):
        self.width = width
        self.height = height

        self.img = Image.new("P", (WIDTH, HEIGHT), Color.WHITE)
        self.img.putpalette(palette)
        self.draw = ImageDraw.Draw(self.img)

    def __load_font(self, font_def: Tuple[Font, int]):
        if font_def not in self.fonts:
            match font_def[0]:
                case Font.ROBOTO_BOLD:
                    self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-bold.ttf", size=font_def[1])
                case Font.ROBOTO_LIGHT:
                    self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-light.ttf", size=font_def[1])
                case Font.ROBOTO_REGULAR:
                    self.fonts[font_def] = ImageFont.truetype("fonts/Roboto-regular.ttf", size=font_def[1])
                case Font.FONT_AWESOME:
                    self.fonts[font_def] = ImageFont.truetype(FontAwesome5FreeSolid, size=font_def[1])
                case _:
                    raise RuntimeError("Invalid font")

        return self.fonts[font_def]

    def render(self, disp_data: DisplayData):
        # clear the canvas
        self.draw.rectangle((0, 0, WIDTH, HEIGHT), fill=Color.WHITE)

        # self.draw.rectangle((left, top, left + icon_space_width, left + icon_space_width), fill=Color.COLOR)

        self.draw_info_icon(0, format_watts(disp_data.solar_current), format_watts(disp_data.solar_today), "sun")
        self.draw_info_icon(1, format_watts(disp_data.import_current), format_watts(disp_data.import_today), "plug")
        self.draw_info_icon(2, format_watts(disp_data.export_current), format_watts(disp_data.export_today), "solar-panel")

        self.draw_graph(disp_data)

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

    def draw_info_icon(self, index: int, text_top: str, text_bottom: str, icon: str):
        bbox = self.info_icon_bbox(index)

        text_height = bbox.height / 4
        icon_height = bbox.height / 2

        # self.draw.rectangle((bbox.topleft, bbox.bottomright), fill=Color.COLOR)

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
        self.show()

    def show(self):
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

        # Draw
        anchor = f"{h_align}{v_align}"
        x, y = bbox.topleft
        match h_align:
            case HAlign.LEFT:
                x = bbox.left
            case HAlign.CENTER:
                x = bbox.centerx
            case HAlign.RIGHT:
                x = bbox.right

        match v_align:
            case VAlign.TOP:
                y = bbox.top
            case VAlign.MIDDLE:
                y = bbox.centery
            case VAlign.BOTTOM:
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
        disp_data.solar_current = data["P"]
        disp_data.solar_today = data["DC"]
        disp_data.append_solar_value(datetime.now(disp_data.timezone), disp_data.solar_current)

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


def subscribe_to_data(user_data: Tuple[DisplayData, DashImage]):
    client = mqtt.Client("statusdisp")
    client.on_message = on_message
    client.user_data_set(user_data)
    client.connect("192.168.1.13")
    client.loop_start()
    (result, _) = client.subscribe([(TOPIC_SOLAR, 0), (TOPIC_NETTO, 0), (TOPIC_IMPORT, 0), (TOPIC_EXPORT, 0)])

    if result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError("Failed to subscribe to mqtt")


if __name__ == "__main__":
    disp_data = DisplayData()
    img = DashImage(WIDTH, HEIGHT, ylw_inky_palette)
    subscribe_to_data((disp_data, img))

    # img.render(disp_data)
    # img.show()
    input("Press Enter to continue.\n")
