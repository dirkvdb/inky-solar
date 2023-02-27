#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#from inky.auto import auto

import json 
from dataclasses import dataclass
from PIL import Image, ImageFont, ImageDraw, ImageColor
from font_source_serif_pro import SourceSerifProSemibold
from font_source_sans_pro import SourceSansProSemibold
from font_font_awesome import FontAwesome5FreeSolid
import fontawesome as fa

import paho.mqtt.client as mqtt

@dataclass
class DisplayData:
    solar_current: float
    solar_today: float

disp_data = DisplayData(0.0, 0.0)

def on_message(client, userdata, message):
    data = json.loads(message.payload)
    userdata.solar_current = data["P"]
    userdata.solar_today = data["DC"]
    
    print(client)
    print(f"Current production: {userdata.solar_current}W")
    print(f"Todays production: {userdata.solar_today / 1000}kWh")

def subcribe_to_data():
    client = mqtt.Client("statusdisp")
    client.on_message=on_message
    client.user_data_set(disp_data)
    client.connect("192.168.1.13")
    client.loop_start()
    client.subscribe("pvpanelendak/PUB/CH1")

# Set up the correct display and scaling factors

#inky_display = auto(ask_user=True, verbose=True)
#inky_display.set_border(inky_display.WHITE)
#inky_display.set_rotation(180)

# This function will take a quote as a string, a width to fit
# it into, and a font (one that's been loaded) and then reflow
# that quote with newlines to fit into the space required.


# def reflow_quote(quote, width, font):
#     words = quote.split(" ")
#     reflowed = '"'
#     line_length = 0

#     for i in range(len(words)):
#         word = words[i] + " "
#         word_length = font.getsize(word)[0]
#         line_length += word_length

#         if line_length < width:
#             reflowed += word
#         else:
#             line_length = word_length
#             reflowed = reflowed[:-1] + "\n  " + word

#     reflowed = reflowed.rstrip() + '"'

#     return reflowed


#WIDTH = inky_display.width
#HEIGHT = inky_display.height
WIDTH = 400
HEIGHT = 300

# Create a new canvas to draw on
ylw_inky_palette = [255, 255, 255,  # 0 = white
                    0, 0, 0,  # 1 = black
                    223, 204, 16]  # index 2 is yellow

img = Image.new("P", (WIDTH, HEIGHT))
img.putpalette(ylw_inky_palette)

draw = ImageDraw.Draw(img)


# Load the fonts

font_size = 24
icon_font_size = 32

author_font = ImageFont.truetype(SourceSerifProSemibold, font_size)
quote_font = ImageFont.truetype(SourceSansProSemibold, font_size)
icon_font = ImageFont.truetype(FontAwesome5FreeSolid, icon_font_size)
white_color = 0
black_color = 1
red_color = 2
#white_color = inky_display.WHITE
#black_color = inky_display.BLACK
#red_color = inky_display.RED

quote_y = 100
author_y = 200

draw.rectangle((0, 0, WIDTH, HEIGHT), fill=white_color)

padding = 50
draw.rectangle(
    (
        padding / 4,
        padding / 4,
        WIDTH - (padding / 4),
        quote_y - (padding / 4)
    ), fill=red_color)

draw.rectangle(
    (
        padding / 4,
        author_y + author_font.getsize("ABCD ")[1] + (padding / 4) + 5,
        WIDTH - (padding / 4),
        HEIGHT - (padding / 4)
    ), fill=red_color)

# Add some white hatching to the red rectangles to make
# it look a bit more interesting

hatch_spacing = 12

for x in range(0, 2 * WIDTH, hatch_spacing):
    draw.line((x, 0, x - WIDTH, HEIGHT), fill=white_color, width=3)

# Write our quote and author to the canvas

draw.text((50, 50), "test", fill=black_color, font=quote_font, align="left")
draw.multiline_text((50, 150), fa.icons["sun"], fill=black_color, font=icon_font, align="left")
draw.multiline_text((100, 150), fa.icons["solar-panel"], fill=black_color, font=icon_font, align="left")
draw.multiline_text((150, 150), fa.icons["plug"], fill=black_color, font=icon_font, align="left")

# Display the completed canvas on Inky wHAT

#inky_display.set_image(img)
#inky_display.show()


if __name__ == "__main__":
    subcribe_to_data()
    input("Press Enter to continue.\n")
    img.convert("RGB").show()