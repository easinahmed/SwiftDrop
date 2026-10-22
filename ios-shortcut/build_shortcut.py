#!/usr/bin/env python3
"""Build the "SwiftDrop" Apple Shortcut for iPhone.

Share a link from any app -> SwiftDrop -> the video or photos are saved on the
iPhone. The shortcut asks free third-party services for the direct media links
(the same idea as the "YAS Download" shortcut), so no computer is involved.
Run on its own, SwiftDrop shows a menu: download the copied link, Settings,
About. Settings are kept in iCloud Drive/Shortcuts/SwiftDrop/settings.json.

This script only uses the Python standard library. It writes the unsigned
workflow as a binary property list and, with --sign, signs it on a Mac:

    python3 ios-shortcut/build_shortcut.py --sign

which runs

    shortcuts sign --mode anyone --input ios-shortcut/build/SwiftDrop-unsigned.shortcut \
                   --output ios-shortcut/dist/SwiftDrop.shortcut

--debug builds "SwiftDrop Debug 1.1" into build/ instead, for testing with
`shortcuts run "<name>" --input-path link.txt` on a Mac. It lists what it found
in iCloud Drive/Shortcuts/SwiftDrop Debug/report.txt instead of saving to
Photos or showing alerts, keeps its settings and Files downloads in that same
folder, accepts a text file as input, and saves a JSON object found in the
input (for example {"quality":"480"}) as its settings before it starts.

The service list lives in SERVICES, YOUTUBE_SERVERS and COBALT_SERVERS below.
The same values are written into a Dictionary at the top of the shortcut, so
they can also be edited later on the iPhone itself.
"""

import argparse
import os
import plistlib
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))

NAME = "SwiftDrop"
VERSION = "1.1"
CREDIT = "Developed by Easin Codes"
WEBSITE = "https://swiftdrop-mac.vercel.app"

# Community cobalt servers that answer API calls without a Turnstile/API key,
# checked live on 2026-10-22 (see README). Every other server listed on
# https://cobalt.directory answers "error.api.auth.jwt.missing".
#
# YouTube: only servers that returned a working video, Short and audio file.
# Ordered by success, then speed; the first two send m4a audio, the last one
# sends opus.
YOUTUBE_SERVERS = [
    "https://rue-cobalt.xenon.zone/",
    "https://co.otomir23.me/",
    "https://api.cobalt.liubquanti.click/",
]
# Every other cobalt site (Facebook, Pinterest, Vimeo...) and the backup for
# TikTok, X, Instagram and Bluesky. cobaltapi.cjs.nz is blocked by YouTube
# ("error.api.youtube.login") but still works for the other sites.
COBALT_SERVERS = [
    "https://rue-cobalt.xenon.zone/",
    "https://co.otomir23.me/",
    "https://cobaltapi.cjs.nz/",
    "https://api.cobalt.liubquanti.click/",
]

# Endpoints of the free services, checked live on 2026-10-22.
SERVICES = [
    ("tiktok_api", "https://www.tikwm.com/api/?hd=1&url="),
    ("x_api", "https://api.fxtwitter.com/status/"),
    ("x_api_backup", "https://api.vxtwitter.com/i/status/"),
    ("instagram_api", "https://www.eeinstagram.com/videos/"),
    ("bluesky_api", "https://d.fxbsky.app"),
    ("bluesky_api_backup", "https://r.bskx.app"),
    ("youtube_servers", "\n".join(YOUTUBE_SERVERS)),
    ("cobalt_servers", "\n".join(COBALT_SERVERS)),
]

# The user's settings, stored as JSON: (key in settings.json, variable in
# the shortcut, default). Every value is text.
SETTINGS = [
    ("save_to", "Save To", "Photos"),      # Photos or Files
    ("folder", "Folder", "SwiftDrop"),     # folder inside iCloud Drive/Shortcuts
    ("quality", "Quality", "720"),         # max, 1080, 720, 480, 360 (cobalt's values)
    ("youtube", "YouTube Mode", "Video"),  # Video or Audio
    ("tiktok_hd", "TikTok HD", "On"),      # On or Off
    ("notify", "Notify", "On"),            # On or Off
]
SETTING_VARIABLE = {key: name for key, name, _ in SETTINGS}
QUALITY_CHOICES = [("Max", "max"), ("1080p", "1080"), ("720p (default)", "720"),
                   ("480p", "480"), ("360p", "360")]
QUALITY_LABELS = [("max", "Max"), ("1080", "1080p"), ("720", "720p"),
                  ("480", "480p"), ("360", "360p")]


class Config:
    """What differs between the shortcut people install and the test copy."""

    def __init__(self, debug):
        self.debug = debug
        if debug:
            self.name = "%s Debug %s" % (NAME, VERSION)
            self.home = "SwiftDrop Debug"
            self.unsigned = os.path.join(HERE, "build", "SwiftDrop Debug-unsigned.shortcut")
            self.signed = os.path.join(HERE, "build", self.name + ".shortcut")
        else:
            self.name = NAME
            self.home = "SwiftDrop"
            self.unsigned = os.path.join(HERE, "build", "SwiftDrop-unsigned.shortcut")
            self.signed = os.path.join(HERE, "dist", "SwiftDrop.shortcut")
        # Paths are relative to the Shortcuts folder in iCloud Drive.
        self.settings_read_path = self.home + "/settings.json"
        self.settings_save_path = "/" + self.home + "/settings.json"
        self.defaults = [(key, name, self.home if key == "folder" else value)
                         for key, name, value in SETTINGS]


# File extensions (lowercase) used to decide what a download is.
MEDIA_EXT = (r"^(mp4|m4v|mov|webm|mkv|3gp|jpe?g|png|gif|webp|heic|heif|avif|"
             r"bmp|tiff?|mp3|m4a|aac|ogg|oga|opus|wav|flac)$")
# "<save_to>:<extension>" of a file that goes to Photos.
TO_PHOTOS = r"^Photos:(mp4|m4v|mov|jpe?g|png|gif|webp|heic|heif)$"
ERROR_EXT = r"^(html?|xhtml|json|txt|xml|rtf|rtfd|webarchive|plist)$"
DIRECT_FILE_TYPE = (r"^(?!.*mpegurl)((video|image|audio)/|application/(pdf|zip|"
                    r"octet-stream|x-zip-compressed|x-rar-compressed|vnd\.rar|"
                    r"x-7z-compressed|gzip|x-gzip|x-tar|epub\+zip|"
                    r"vnd\.android\.package-archive|x-apple-diskimage))")
# A file size such as "742 KB" contains a non-zero digit (Western, Arabic,
# Persian, Devanagari or Bengali); "Zero KB" or "0 bytes" does not.
NONZERO_DIGIT = "[1-9\u0661-\u0669\u06f1-\u06f9\u0967-\u096f\u09e7-\u09ef]"
# A folder name typed in Settings: one path part, no surrounding spaces.
FOLDER_NAME = r"[^/\s](?:[^/]*[^/\s])?"
JSON_OBJECT = r"\{[\s\S]*\}"

# Platform detection on the full shared URL. The X, Instagram and Bluesky
# patterns also capture the post id used by the dedicated services.
X_LINK = (r"(?:^|[/.])(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx)\.com/"
          r"[^/?#]+/status(?:es)?/(\d+)")
TIKTOK_LINK = r"(?:^|[/.])tiktok\.com/"
INSTAGRAM_LINK = (r"(?:^|[/.])(?:instagram\.com|instagr\.am)/(?:[A-Za-z0-9_.]+/)?"
                  r"(?:p|reels?|tv)/([A-Za-z0-9_-]+)")
BLUESKY_LINK = r"(?:^|[/.])bsky\.app/profile/([^/?#]+)/post/([A-Za-z0-9]+)"
COBALT_LINK = (r"(?:^|[/.])(?:facebook\.com|fb\.watch|"
               r"pinterest\.[a-z.]+|pin\.it|twitch\.tv|vimeo\.com|reddit\.com|"
               r"redd\.it|soundcloud\.com|tumblr\.com|snapchat\.com|"
               r"dailymotion\.com|dai\.ly|streamable\.com|bilibili\.com|b23\.tv|"
               r"loom\.com|ok\.ru|vk\.com|vkvideo\.ru|rutube\.ru|"
               r"newgrounds\.com|threads\.(?:net|com))/")
YOUTUBE_LINK = r"(?:^|[/.])(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/"


def le_number(limit):
    """Regex for a whole number from 1 to limit (no leading zeros)."""
    digits = str(limit)
    size = len(digits)
    options = []
    if size > 1:
        options.append("[1-9]" + ("\\d{0,%d}" % (size - 2) if size > 2 else ""))
    for i, char in enumerate(digits):
        low = 1 if i == 0 else 0
        if int(char) > low:
            high = int(char) - 1
            group = str(low) if high == low else "[%d-%d]" % (low, high)
            rest = size - i - 1
            options.append(digits[:i] + group + ("\\d{%d}" % rest if rest else ""))
    options.append(digits)
    return "(?:" + "|".join(options) + ")"


def x_format_pattern(limit):
    """An X video link (.../vid/[avc1/]WIDTHxHEIGHT/...) whose short side is <= limit."""
    small = le_number(limit)
    return (r"https?://\S+?/vid/(?:[^/\s]+/)?(?:%sx\d+|\d+x%s)/\S+" % (small, small))


# Qualities that limit the X video size; "max" keeps the best one.
X_QUALITIES = [value for _, value in QUALITY_CHOICES if value != "max"]

FAILURE_MESSAGE = ("Couldn't download this link. The free download services may "
                   "be down or don't support this site. Try again later.")
YOUTUBE_FAILURE = ("YouTube is blocking the free download servers right now. "
                   "Please try again later.")
# When a server says the video itself can't be had (cobalt's
# error.api.content.video.unavailable / private / age / live / region).
YOUTUBE_UNAVAILABLE = ("This YouTube video can't be downloaded. It may be "
                       "private, age-restricted, live or removed.")

MENU_DOWNLOAD = "Download link from clipboard"
MENU_SETTINGS = "Settings"
MENU_ABOUT = "About"


def host(url):
    return url.split("://", 1)[1].strip("/")


def about_text(cfg):
    servers = []
    for url in YOUTUBE_SERVERS + COBALT_SERVERS:
        if host(url) not in servers:
            servers.append(host(url))
    return ("Version " + VERSION + "\n" + CREDIT + "\n" + WEBSITE + "\n\n"
            "Privacy: the link you download is sent to free third-party "
            "services: tikwm.com, fxtwitter.com, vxtwitter.com, eeinstagram.com, "
            "fxbsky.app, bskx.app and the community cobalt servers "
            + ", ".join(servers) + ". They see the link. SwiftDrop sends nothing "
            "else: no account, no contacts, no files.\n\n"
            "Settings are saved in iCloud Drive > Shortcuts > " + cfg.home
            + " > settings.json.")


OBJ = "\ufffc"  # placeholder for a variable inside a text field

ICON_GLYPH_DOWNLOAD_ARROW = 59693
ICON_COLOR_BLUE = 463140863


_uuid_counter = [0]


def new_uuid():
    """Stable UUIDs, so rebuilding the same shortcut gives the same file."""
    _uuid_counter[0] += 1
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "swiftdrop/%d" % _uuid_counter[0])).upper()


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


# ---------------------------------------------------------------------------
# Value helpers (how Shortcuts serialises variables and text fields)
# ---------------------------------------------------------------------------

def output(action_uuid, name):
    """Reference to the output of an earlier action (a magic variable)."""
    return {"Type": "ActionOutput", "OutputUUID": action_uuid, "OutputName": name}


def variable(name):
    """Reference to a named variable, or to Repeat Item / Repeat Item 2."""
    return {"Type": "Variable", "VariableName": name}


SHORTCUT_INPUT = {"Type": "ExtensionInput"}


def attachment(ref):
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def text_field(*parts):
    """A text field mixing literal strings and variable references."""
    string = ""
    ranges = {}
    for part in parts:
        if isinstance(part, str):
            string += part
        else:
            ranges["{%d, 1}" % utf16_len(string)] = part
            string += OBJ
    value = {"string": string}
    if ranges:
        value["attachmentsByRange"] = ranges
    return {"Value": value, "WFSerializationType": "WFTextTokenString"}


def dictionary_field(pairs):
    """Text-only dictionary (Dictionary action, headers, JSON body)."""
    items = []
    for key, value in pairs:
        if not isinstance(value, tuple):
            value = (value,)
        items.append({
            "WFItemType": 0,
            "WFKey": text_field(key),
            "WFValue": text_field(*value),
        })
    return {"Value": {"WFDictionaryFieldValueItems": items},
            "WFSerializationType": "WFDictionaryFieldValue"}


# Condition codes of the "If" action (single-condition form, iOS 15+).
IS = 4
IS_GREATER_THAN = 2
HAS_ANY_VALUE = 100
HAS_NO_VALUE = 101


class Shortcut:
    def __init__(self, cfg):
        self.cfg = cfg
        self.debug = cfg.debug
        self.actions = []
        self.repeat_depth = 0

    # -- plumbing ----------------------------------------------------------
    def add(self, identifier, params, output_name=None):
        params = dict(params)
        ref = None
        if output_name:
            params["UUID"] = new_uuid()
            ref = output(params["UUID"], output_name)
        self.actions.append({
            "WFWorkflowActionIdentifier": "is.workflow.actions." + identifier,
            "WFWorkflowActionParameters": params,
        })
        return ref

    # -- control flow ------------------------------------------------------
    def if_start(self, ref, condition, string=None, number=None):
        group = new_uuid()
        params = {
            "GroupingIdentifier": group,
            "WFControlFlowMode": 0,
            "WFCondition": condition,
            "WFInput": {"Type": "Variable", "Variable": attachment(ref)},
        }
        if string is not None:
            params["WFConditionalActionString"] = string
        if number is not None:
            params["WFNumberValue"] = number
        self.add("conditional", params)
        return group

    def otherwise(self, group):
        self.add("conditional", {"GroupingIdentifier": group, "WFControlFlowMode": 1})

    def end_if(self, group):
        """End If; returns the If Result (output of the branch that ran)."""
        end = new_uuid()
        self.add("conditional", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                 "UUID": end})
        return output(end, "If Result")

    def repeat_start(self, ref):
        """Start Repeat with Each; returns (group, Repeat Item reference)."""
        group = new_uuid()
        self.add("repeat.each", {"GroupingIdentifier": group, "WFControlFlowMode": 0,
                                 "WFInput": attachment(ref)})
        self.repeat_depth += 1
        name = "Repeat Item" if self.repeat_depth == 1 else "Repeat Item %d" % self.repeat_depth
        return group, variable(name)

    def repeat_end(self, group):
        """End Repeat; returns Repeat Results (last output of every pass)."""
        self.repeat_depth -= 1
        end = new_uuid()
        self.add("repeat.each", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                 "UUID": end})
        return output(end, "Repeat Results")

    def repeat_times_start(self, count):
        """Start Repeat N times; returns (group, Repeat Index reference)."""
        group = new_uuid()
        self.add("repeat.count", {"GroupingIdentifier": group, "WFControlFlowMode": 0,
                                  "WFRepeatCount": count})
        self.repeat_depth += 1
        name = "Repeat Index" if self.repeat_depth == 1 else "Repeat Index %d" % self.repeat_depth
        return group, variable(name)

    def repeat_times_end(self, group):
        self.repeat_depth -= 1
        self.add("repeat.count", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                  "UUID": new_uuid()})

    def menu_start(self, prompt, titles):
        """Choose from Menu with fixed item titles; prompt may hold variables."""
        group = new_uuid()
        if isinstance(prompt, str):
            prompt_value = prompt
        else:
            prompt_value = text_field(*prompt)
        self.add("choosefrommenu", {"GroupingIdentifier": group, "WFControlFlowMode": 0,
                                    "WFMenuPrompt": prompt_value,
                                    "WFMenuItems": list(titles)})
        return group

    def menu_case(self, group, title):
        self.add("choosefrommenu", {"GroupingIdentifier": group, "WFControlFlowMode": 1,
                                    "WFMenuItemTitle": title})

    def menu_end(self, group):
        self.add("choosefrommenu", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                    "UUID": new_uuid()})

    # -- actions -----------------------------------------------------------
    def comment(self, text):
        self.add("comment", {"WFCommentActionText": text})

    def text(self, *parts):
        return self.add("gettext", {"WFTextActionText": text_field(*parts)}, "Text")

    def nothing(self):
        self.add("nothing", {})

    def set_variable(self, name, ref):
        self.add("setvariable", {"WFVariableName": name, "WFInput": attachment(ref)})

    def add_to_variable(self, name, ref):
        self.add("appendvariable", {"WFVariableName": name, "WFInput": attachment(ref)})

    def get_urls(self, ref):
        return self.add("detect.link", {"WFInput": text_field(ref)}, "URLs")

    def first_item(self, ref):
        return self.add("getitemfromlist", {"WFItemSpecifier": "First Item",
                                            "WFInput": attachment(ref)}, "Item from List")

    def last_item(self, ref):
        return self.add("getitemfromlist", {"WFItemSpecifier": "Last Item",
                                            "WFInput": attachment(ref)}, "Item from List")

    def get_clipboard(self):
        return self.add("getclipboard", {}, "Clipboard")

    def ask_text(self, prompt, default_ref):
        return self.add("ask", {"WFAskActionPrompt": prompt, "WFInputType": "Text",
                                "WFAskActionDefaultAnswer": text_field(default_ref)},
                        "Provided Input")

    def alert(self, title, message):
        if self.debug:
            # A test run can't press OK; report the message as the output.
            self.report("ALERT: ", message)
            return
        self.add("alert", {"WFAlertActionTitle": text_field(title),
                           "WFAlertActionMessage": text_field(message),
                           "WFAlertActionCancelButtonShown": False})

    def stop(self):
        self.add("exit", {})

    def dictionary(self, pairs):
        return self.add("dictionary", {"WFItems": dictionary_field(pairs)}, "Dictionary")

    def dictionary_value(self, ref, key):
        """Value for a key; key is a string or a variable reference."""
        if not isinstance(key, str):
            key = text_field(key)
        return self.add("getvalueforkey", {"WFGetDictionaryValueType": "Value",
                                           "WFDictionaryKey": key,
                                           "WFInput": attachment(ref)}, "Dictionary Value")

    def split_lines(self, ref):
        return self.add("text.split", {"text": text_field(ref),
                                       "WFTextSeparator": "New Lines"}, "Split Text")

    def match(self, pattern, *text_parts):
        return self.add("text.match", {"WFMatchTextPattern": pattern,
                                       "text": text_field(*text_parts),
                                       "WFMatchTextCaseSensitive": False}, "Matches")

    def match_group(self, matches_ref, index):
        return self.add("text.match.getgroup", {"matches": attachment(matches_ref),
                                                "WFGetGroupType": "Group At Index",
                                                "WFGroupIndex": index}, "Group")

    def get_dictionary(self, ref):
        return self.add("detect.dictionary", {"WFInput": attachment(ref)}, "Dictionary")

    def url_encode(self, ref):
        return self.add("urlencode", {"WFEncodeMode": "Encode",
                                      "WFInput": text_field(ref)}, "URL Encoded Text")

    def get_contents(self, url_parts, headers=None, json_body=None):
        params = {"WFURL": text_field(*url_parts), "WFHTTPMethod": "GET"}
        if json_body is not None:
            params["WFHTTPMethod"] = "POST"
            params["WFHTTPBodyType"] = "JSON"
            params["WFJSONValues"] = dictionary_field(json_body)
        if headers is not None:
            params["ShowHeaders"] = True
            params["WFHTTPHeaders"] = dictionary_field(headers)
        return self.add("downloadurl", params, "Contents of URL")

    def headers_of_url(self, ref):
        return self.add("url.getheaders", {"WFInput": text_field(ref)}, "Headers of URL")

    def file_detail(self, ref, detail):
        return self.add("properties.files", {"WFContentItemPropertyName": detail,
                                             "WFInput": attachment(ref)}, detail)

    def set_name(self, ref, *name_parts):
        return self.add("setitemname", {"WFInput": attachment(ref),
                                        "WFName": text_field(*name_parts)}, "Renamed Item")

    def save_to_photos(self, ref):
        self.add("savetocameraroll", {"WFInput": attachment(ref)})

    def get_file(self, path):
        """Get File from the Shortcuts folder in iCloud Drive, no picker.

        Returns nothing (instead of stopping) when the file isn't there.
        """
        return self.add("documentpicker.open", {"WFShowFilePicker": False,
                                                "WFGetFilePath": text_field(path),
                                                "WFFileErrorIfNotFound": False}, "File")

    def save_file(self, ref, path_parts, overwrite):
        """Save File into the Shortcuts folder in iCloud Drive, without asking."""
        self.add("documentpicker.save", {"WFInput": attachment(ref),
                                         "WFAskWhereToSave": False,
                                         "WFFileDestinationPath": text_field(*path_parts),
                                         "WFSaveFileOverwrite": overwrite}, "Saved File")

    def count(self, ref):
        # Apple saves this action's input as "Input"; newer builds also read WFInput.
        return self.add("count", {"WFCountType": "Items", "Input": attachment(ref),
                                  "WFInput": attachment(ref)}, "Count")

    def notification(self, title, *body_parts):
        self.add("notification", {"WFNotificationActionTitle": text_field(title),
                                  "WFNotificationActionBody": text_field(*body_parts),
                                  "WFNotificationActionSound": True})

    # -- debug reporting -----------------------------------------------------
    def log(self, *parts):
        """Debug build only: add a line to the report."""
        if self.debug:
            self.add_to_variable("Log", self.text(*parts))

    def report(self, *parts):
        """Debug build only: end the run with the report as the output.

        The report is also saved as report.txt (`shortcuts run --output-path`
        stays empty on macOS 27).
        """
        home = "/" + self.cfg.home + "/"
        text = self.text(self.cfg.name, "\nlink: ", variable("Link"),
                         "\nplatform: ", variable("Platform"),
                         "\nsettings: ", variable("Settings"), "\n", *parts,
                         "\n--- log\n", variable("Log"))
        self.save_file(self.set_name(text, "report.txt"), [home + "report.txt"],
                       overwrite=True)
        self.add("output", {"WFOutput": text_field(text)})

    # -- SwiftDrop building blocks -------------------------------------------
    def if_has_items(self, ref):
        """If the value holds at least one item.

        Counting is used because a Text action holding an empty string still
        "has any value" (seen on a live run), and Get Dictionary Value returns
        nothing for missing or null JSON keys, which counts as 0.
        """
        return self.if_start(self.count(ref), IS_GREATER_THAN, number="0")

    def if_nothing_saved_yet(self):
        return self.if_start(variable("Files"), HAS_NO_VALUE)

    def download_media(self, url_parts, source, fallback_name=None, check_size=False,
                       name=None):
        """Download one URL and add it to "Files" only if it is real media.

        A download that is a web page or JSON error is dropped, so the next
        service in the chain still gets a turn. fallback_name renames files
        whose type Shortcuts couldn't tell (for example cobalt's tunnels,
        which send a file name but no Content-Type). name renames every
        download that isn't an error page (cobalt's file name: its m4a audio
        arrives as audio/mp4, which Shortcuts would call .mp4). check_size
        drops empty files (a cobalt tunnel that YouTube cut off is 0 bytes).
        """
        file_ref = self.add("downloadurl",
                            {"WFURL": text_field(*url_parts), "WFHTTPMethod": "GET"},
                            "Contents of URL")
        got_file = self.if_start(file_ref, HAS_ANY_VALUE)
        size_ok = None
        if check_size:
            size = self.file_detail(file_ref, "File Size")
            size_ok = self.if_start(self.match(NONZERO_DIGIT, size), HAS_ANY_VALUE)
        ext = self.file_detail(file_ref, "File Extension")
        if name is not None:
            not_error = self.if_start(self.match(ERROR_EXT, ext), HAS_NO_VALUE)
            self.add_to_variable("Files", self.set_name(file_ref, *name))
            self.log("saved (named) from ", *source)
            self.end_if(not_error)
        else:
            is_media = self.if_start(self.match(MEDIA_EXT, ext), HAS_ANY_VALUE)
            self.add_to_variable("Files", file_ref)
            self.log("saved from ", *source)
            if fallback_name is not None:
                self.otherwise(is_media)
                is_error = self.if_start(self.match(ERROR_EXT, ext), HAS_NO_VALUE)
                renamed = self.set_name(file_ref, *fallback_name)
                self.add_to_variable("Files", renamed)
                self.log("saved (renamed) from ", *source)
                self.end_if(is_error)
            self.end_if(is_media)
        if size_ok is not None:
            if self.debug:
                self.otherwise(size_ok)
                self.log("empty file from ", *source)
            self.end_if(size_ok)
        self.end_if(got_file)

    def settings_dictionary(self):
        """The current settings as a Dictionary (from the setting variables)."""
        return self.dictionary([(key, (variable(name),)) for key, name, _ in SETTINGS])

    def save_json(self, json_ref):
        """Write JSON text to settings.json (no picker, overwrite).

        Seen on a Mac: Save File swaps the extension in the path for the
        item's own type (plain Text became settings.txt), so the text is named
        settings.json first, which makes it a JSON file. A full path also
        creates the folder; a path to a folder that doesn't exist yet saves
        a file named after the folder instead.
        """
        named = self.set_name(json_ref, "settings.json")
        self.save_file(named, [self.cfg.settings_save_path], overwrite=True)

    def save_settings(self):
        self.save_json(self.text(self.settings_dictionary()))

    def change_setting(self, key, value_ref):
        """Keep a new value (as Text) and save all settings."""
        self.set_variable(SETTING_VARIABLE[key], self.text(value_ref))
        self.save_settings()

    def choose_setting(self, key, prompt, choices):
        """A menu of fixed choices that stores the picked value under key."""
        menu = self.menu_start(prompt, [label for label, _ in choices])
        for label, value in choices:
            self.menu_case(menu, label)
            self.set_variable("Choice", self.text(value))
        self.menu_end(menu)
        self.change_setting(key, variable("Choice"))

    def pick_x_video(self, item):
        """Download one X photo or video, at most the chosen video quality.

        FixTweet lists every MP4 size of a video under "formats"; the link
        holds the size (.../vid/1280x720/...). The largest size whose short
        side fits the setting is used (formats come smallest first), else
        the default link (the best size).
        """
        best = self.dictionary_value(item, "url")
        formats = self.dictionary_value(item, "formats")
        loop, fmt = self.repeat_start(formats)
        self.dictionary_value(fmt, "url")
        format_links = self.text(self.repeat_end(loop))
        groups = []
        for quality in X_QUALITIES:
            group = self.if_start(variable("Quality"), IS, quality)
            self.match(x_format_pattern(int(quality)), format_links)
            self.otherwise(group)
            groups.append(group)
        self.nothing()
        fitting = None
        for group in reversed(groups):
            fitting = self.end_if(group)
        picked = self.last_item(fitting)
        has_pick = self.if_has_items(picked)
        self.download_media([picked], ("fxtwitter (sized)",))
        self.otherwise(has_pick)
        self.download_media([best], ("fxtwitter",))
        self.end_if(has_pick)


def build_settings_menu(s):
    """The Settings screen: a menu that shows the current values, until Done."""
    labels = s.dictionary(QUALITY_LABELS)
    loop, _ = s.repeat_times_start(40)
    still_open = s.if_start(variable("Settings Done"), HAS_NO_VALUE)
    value = {key: variable(name) for key, name, _ in SETTINGS}
    quality_label = s.dictionary_value(labels, value["quality"])
    menu = s.menu_start(
        ("SwiftDrop Settings\n\n"
         "Save videos & photos to: ", value["save_to"],
         "\nFiles folder: ", value["folder"],
         "\nVideo quality: ", quality_label,
         "\nYouTube: ", value["youtube"],
         "\nTikTok HD: ", value["tiktok_hd"],
         "\nNotification when done: ", value["notify"]),
        ["Save videos & photos to", "Files folder name", "Video quality",
         "YouTube: download as", "TikTok: HD when available",
         "Show a notification when done", "Reset settings", "Done"])

    s.menu_case(menu, "Save videos & photos to")
    s.choose_setting("save_to", "Save videos and photos to",
                     [("Photos", "Photos"), ("Files (folder in Settings)", "Files")])

    s.menu_case(menu, "Files folder name")
    typed = s.ask_text("Folder for downloads, inside iCloud Drive > Shortcuts. "
                       "Files that aren't videos or photos always go here.",
                       value["folder"])
    clean = s.first_item(s.match(FOLDER_NAME, typed))
    has_name = s.if_has_items(clean)
    s.change_setting("folder", clean)
    s.end_if(has_name)

    s.menu_case(menu, "Video quality")
    s.choose_setting("quality", "Video quality (used when the site offers a choice)",
                     QUALITY_CHOICES)

    s.menu_case(menu, "YouTube: download as")
    s.choose_setting("youtube", "YouTube: download as",
                     [("Video", "Video"), ("Audio only (m4a)", "Audio")])

    s.menu_case(menu, "TikTok: HD when available")
    s.choose_setting("tiktok_hd", "TikTok: HD video when available",
                     [("On", "On"), ("Off (smaller files)", "Off")])

    s.menu_case(menu, "Show a notification when done")
    s.choose_setting("notify", "Show a notification when done",
                     [("On", "On"), ("Off", "Off")])

    s.menu_case(menu, "Reset settings")
    for _, name, default in s.cfg.defaults:
        s.set_variable(name, s.text(default))
    s.save_settings()

    s.menu_case(menu, "Done")
    s.set_variable("Settings Done", s.text("yes"))
    s.menu_end(menu)
    s.end_if(still_open)
    s.repeat_times_end(loop)


def build_actions(cfg):
    _uuid_counter[0] = 0
    s = Shortcut(cfg)

    # ------------------------------------------------------------------ intro
    s.comment(
        "SwiftDrop for iPhone " + VERSION + "\n" + CREDIT + "\n" + WEBSITE + "\n\n"
        "Share a link from TikTok, Instagram, YouTube, X, Facebook, Pinterest, "
        "Bluesky, Vimeo or Twitch to SwiftDrop. Videos and photos are saved to "
        "Photos (or Files, see Settings); other files (audio, zip, pdf) go to "
        "Files > iCloud Drive > Shortcuts > SwiftDrop.\n"
        "Run SwiftDrop on its own for the menu: download the copied link, "
        "Settings, About.\n\n"
        "Privacy: the link you share is sent to free third-party download "
        "services (tikwm.com, fxtwitter.com, vxtwitter.com, eeinstagram.com, "
        "fxbsky.app, bskx.app and the cobalt servers below). They see the link "
        "and can stop working at any time.")
    if cfg.debug:
        s.comment("DEBUG COPY: reports what it found instead of saving to Photos. "
                  "Delete it when testing is done.")

    # --------------------------------------------------------------- services
    s.comment(
        "SERVICES: where SwiftDrop asks for the real media link. If one stops "
        "working, replace its address here.\n"
        "youtube_servers and cobalt_servers: community cobalt servers, one per "
        "line, tried in order until one works. Only servers that need no "
        "Turnstile check or API key work here (cobalt.directory, Turnstile "
        "column shows a cross).")
    s.set_variable("Services", s.dictionary(SERVICES))

    # --------------------------------------------------------------- settings
    s.comment(
        "SETTINGS: defaults, then the choices saved from the menu in "
        "iCloud Drive > Shortcuts > " + cfg.home + " > settings.json.")
    # Every value goes through a Text action: an "If ... is" on a value taken
    # straight from a dictionary stops with "Please choose a value for each
    # parameter" (seen on macOS 27), and actions such as Match Text can't read
    # it either.
    for _, name, default in cfg.defaults:
        s.set_variable(name, s.text(default))

    if cfg.debug:
        s.comment("DEBUG: a JSON object in the input is saved as settings.json "
                  "first, the same way the Settings menu saves it.")
        found = s.match(JSON_OBJECT, SHORTCUT_INPUT)
        has_json = s.if_start(found, HAS_ANY_VALUE)
        s.save_json(s.text(s.first_item(found)))
        s.log("saved test settings")
        s.end_if(has_json)

    saved = s.get_file(cfg.settings_read_path)
    has_saved = s.if_start(saved, HAS_ANY_VALUE)
    stored = s.get_dictionary(saved)
    for key, name, _ in SETTINGS:
        stored_value = s.dictionary_value(stored, key)
        has_value = s.if_has_items(stored_value)
        s.set_variable(name, s.text(stored_value))
        s.end_if(has_value)
    s.end_if(has_saved)
    s.set_variable("Settings", s.settings_dictionary())
    s.log("settings in use: ", variable("Settings"))

    # ------------------------------------------------------------------ input
    s.comment("From the share sheet: use the shared link. Run on its own: "
              "show the menu.")
    s.set_variable("Link", s.first_item(s.get_urls(SHORTCUT_INPUT)))
    run_directly = s.if_start(SHORTCUT_INPUT, HAS_NO_VALUE)
    menu = s.menu_start(NAME + " " + VERSION, [MENU_DOWNLOAD, MENU_SETTINGS, MENU_ABOUT])
    s.menu_case(menu, MENU_DOWNLOAD)
    clipboard = s.get_clipboard()
    s.set_variable("Link", s.first_item(s.get_urls(clipboard)))
    no_link = s.if_start(variable("Link"), HAS_NO_VALUE)
    answer = s.ask_text("Paste the link to download", clipboard)
    s.set_variable("Link", s.first_item(s.get_urls(answer)))
    s.end_if(no_link)
    s.menu_case(menu, MENU_SETTINGS)
    build_settings_menu(s)
    s.stop()
    s.menu_case(menu, MENU_ABOUT)
    s.alert(NAME + " " + VERSION, about_text(cfg))
    s.stop()
    s.menu_end(menu)
    s.end_if(run_directly)

    still_no_link = s.if_start(variable("Link"), HAS_NO_VALUE)
    s.alert(NAME, "No link found. Share a link to SwiftDrop, or copy one and "
                  "run SwiftDrop again.")
    s.stop()
    s.end_if(still_no_link)

    # --------------------------------------------------------------- platform
    s.comment("Work out which site the link is from.")
    s.set_variable("Platform", s.text("other"))
    platform_matches = {}
    for name, pattern in (("x", X_LINK), ("tiktok", TIKTOK_LINK),
                          ("instagram", INSTAGRAM_LINK), ("bluesky", BLUESKY_LINK),
                          ("cobalt", COBALT_LINK), ("youtube", YOUTUBE_LINK)):
        matches = s.match(pattern, variable("Link"))
        platform_matches[name] = matches
        found = s.if_start(matches, HAS_ANY_VALUE)
        s.set_variable("Platform", s.text(name))
        s.end_if(found)

    # ----------------------------------------------------------------- TikTok
    s.comment("TikTok: tikwm.com gives the video without watermark (HD when "
              "available, see Settings), or every photo of a slideshow.")
    is_tiktok = s.if_start(variable("Platform"), IS, "tiktok")
    encoded = s.url_encode(variable("Link"))
    api = s.dictionary_value(variable("Services"), "tiktok_api")
    reply = s.get_dictionary(s.get_contents([api, encoded]))
    # Step by step: a key path such as "data.images" stops the shortcut when
    # "data" is missing (tikwm's error replies have no "data").
    data = s.dictionary_value(reply, "data")
    has_data = s.if_has_items(data)
    images = s.dictionary_value(data, "images")
    has_images = s.if_has_items(images)
    loop, item = s.repeat_start(images)
    s.download_media([item], ("tikwm photo",), fallback_name=("TikTok photo.jpg",))
    s.repeat_end(loop)
    s.otherwise(has_images)
    hd_video = s.dictionary_value(data, "hdplay")
    sd_video = s.dictionary_value(data, "play")
    hd_off = s.if_start(variable("TikTok HD"), IS, "Off")
    s.set_variable("TikTok First", sd_video)
    s.set_variable("TikTok Second", hd_video)
    s.otherwise(hd_off)
    s.set_variable("TikTok First", hd_video)
    s.set_variable("TikTok Second", sd_video)
    s.end_if(hd_off)
    for name in ("TikTok First", "TikTok Second"):
        not_yet = s.if_nothing_saved_yet()
        has_video = s.if_has_items(variable(name))
        s.download_media([variable(name)], ("tikwm ", name),
                         fallback_name=("TikTok video.mp4",))
        s.end_if(has_video)
        s.end_if(not_yet)
    s.end_if(has_images)
    s.end_if(has_data)
    s.end_if(is_tiktok)

    # ---------------------------------------------------------------------- X
    s.comment("X / Twitter: FixTweet (fxtwitter) lists every video, GIF and "
              "photo of the post, in every size; vxtwitter is the backup.")
    is_x = s.if_start(variable("Platform"), IS, "x")
    post_id = s.match_group(platform_matches["x"], 1)
    api = s.dictionary_value(variable("Services"), "x_api")
    reply = s.get_dictionary(s.get_contents([api, post_id]))
    tweet = s.dictionary_value(reply, "tweet")
    has_tweet = s.if_has_items(tweet)
    media = s.dictionary_value(tweet, "media")
    has_media = s.if_has_items(media)
    every_item = s.dictionary_value(media, "all")
    has_items = s.if_has_items(every_item)
    loop, item = s.repeat_start(every_item)
    s.pick_x_video(item)
    s.repeat_end(loop)
    s.end_if(has_items)
    s.end_if(has_media)
    s.end_if(has_tweet)

    backup = s.if_nothing_saved_yet()
    api = s.dictionary_value(variable("Services"), "x_api_backup")
    reply = s.get_dictionary(s.get_contents([api, post_id]))
    media = s.dictionary_value(reply, "mediaURLs")
    has_media = s.if_has_items(media)
    loop, item = s.repeat_start(media)
    s.download_media([item], ("vxtwitter",))
    s.repeat_end(loop)
    s.end_if(has_media)
    s.end_if(backup)
    s.end_if(is_x)

    # ---------------------------------------------------------------- Bluesky
    s.comment("Bluesky: fxbsky.app and bskx.app send the post's video or photo "
              "straight back.")
    is_bluesky = s.if_start(variable("Platform"), IS, "bluesky")
    handle = s.match_group(platform_matches["bluesky"], 1)
    post = s.match_group(platform_matches["bluesky"], 2)
    for key in ("bluesky_api", "bluesky_api_backup"):
        not_yet = s.if_nothing_saved_yet()
        api = s.dictionary_value(variable("Services"), key)
        s.download_media([api, "/profile/", handle, "/post/", post], (key,))
        s.end_if(not_yet)
    s.end_if(is_bluesky)

    # -------------------------------------------------------------- Instagram
    s.comment("Instagram: InstaFix (eeinstagram.com) sends each photo or video "
              "of the post in turn (1, 2, 3...) until there are no more. Its "
              "links work in Shortcuts, unlike some long Instagram links that "
              "Shortcuts cuts short.")
    is_instagram = s.if_start(variable("Platform"), IS, "instagram")
    code = s.match_group(platform_matches["instagram"], 1)
    api = s.dictionary_value(variable("Services"), "instagram_api")
    loop, index = s.repeat_times_start(20)
    more = s.if_start(variable("Instagram Done"), HAS_NO_VALUE)
    item = s.add("downloadurl", {"WFURL": text_field(api, code, "/", index),
                                 "WFHTTPMethod": "GET"}, "Contents of URL")
    got_item = s.if_start(item, HAS_ANY_VALUE)
    ext = s.file_detail(item, "File Extension")
    is_media = s.if_start(s.match(MEDIA_EXT, ext), HAS_ANY_VALUE)
    s.add_to_variable("Files", item)
    s.log("saved from instafix ", index)
    s.otherwise(is_media)
    s.set_variable("Instagram Done", s.text("yes"))
    s.end_if(is_media)
    s.otherwise(got_item)
    s.set_variable("Instagram Done", s.text("yes"))
    s.end_if(got_item)
    s.end_if(more)
    s.repeat_times_end(loop)
    s.end_if(is_instagram)

    # ----------------------------------------------------------- direct files
    s.comment("Any other link: if it already points at a video, photo, audio "
              "or document file, download it as it is.")
    is_other = s.if_start(variable("Platform"), IS, "other")
    headers = s.headers_of_url(variable("Link"))
    content_type = s.text(s.dictionary_value(headers, "Content-Type"),
                          s.dictionary_value(headers, "content-type"))
    is_file = s.if_start(s.match(DIRECT_FILE_TYPE, content_type), HAS_ANY_VALUE)
    direct = s.get_contents([variable("Link")])
    s.add_to_variable("Files", direct)
    s.log("saved direct file ", content_type)
    s.end_if(is_file)
    s.end_if(is_other)

    # ----------------------------------------------------------------- cobalt
    s.comment("cobalt servers: YouTube, Facebook, Pinterest, Twitch, Vimeo "
              "and the rest, and the backup for every site above. Each server "
              "is tried in turn until something is saved. A server that answers "
              "with an error (YouTube blocked it, rate limit, unsupported link) "
              "or an empty file is skipped. Shortcuts can't skip a server that "
              "doesn't answer at all, so the most reliable one is first.")
    nothing_yet = s.if_nothing_saved_yet()
    is_youtube = s.if_start(variable("Platform"), IS, "youtube")
    servers = s.dictionary_value(variable("Services"), "youtube_servers")
    s.set_variable("Cobalt Servers", s.get_urls(servers))
    audio = s.if_start(variable("YouTube Mode"), IS, "Audio")
    s.set_variable("Mode", s.text("audio"))
    s.otherwise(audio)
    s.set_variable("Mode", s.text("auto"))
    s.end_if(audio)
    s.otherwise(is_youtube)
    servers = s.dictionary_value(variable("Services"), "cobalt_servers")
    s.set_variable("Cobalt Servers", s.get_urls(servers))
    s.set_variable("Mode", s.text("auto"))
    s.end_if(is_youtube)

    loop, server = s.repeat_start(variable("Cobalt Servers"))
    not_yet = s.if_nothing_saved_yet()
    reply = s.get_contents(
        [server],
        headers=[("Accept", "application/json"), ("Content-Type", "application/json")],
        json_body=[("url", (variable("Link"),)), ("videoQuality", (variable("Quality"),)),
                   ("youtubeVideoCodec", "h264"), ("downloadMode", (variable("Mode"),)),
                   ("audioFormat", "best")])
    reply_text = s.text(reply)
    reply = s.get_dictionary(reply)
    # Through a Text action, so "If ... is" compares text (an If on a
    # Dictionary Value straight away stops with "choose a value" on a Mac).
    status = s.text(s.dictionary_value(reply, "status"))
    s.log("cobalt ", server, " ", reply_text)
    is_error = s.if_start(status, IS, "error")
    s.comment("cobalt said no (e.g. error.api.youtube.login, fetch.fail, "
              "rate limit): try the next server.")
    s.add_to_variable("Cobalt Errors", reply_text)
    s.otherwise(is_error)
    single = s.dictionary_value(reply, "url")
    has_single = s.if_has_items(single)
    given_name = s.dictionary_value(reply, "filename")
    filename = s.text(given_name)
    has_name = s.if_has_items(given_name)
    s.download_media([single], ("cobalt ", server), name=(filename,), check_size=True)
    s.otherwise(has_name)
    s.download_media([single], ("cobalt ", server), check_size=True)
    s.end_if(has_name)
    s.otherwise(has_single)
    picker = s.dictionary_value(reply, "picker")
    has_picker = s.if_has_items(picker)
    inner, choice = s.repeat_start(picker)
    s.download_media([s.dictionary_value(choice, "url")], ("cobalt picker ", server))
    s.repeat_end(inner)
    s.end_if(has_picker)
    s.end_if(has_single)
    s.end_if(is_error)
    s.end_if(not_yet)
    s.repeat_end(loop)
    s.end_if(nothing_yet)

    # ----------------------------------------------------------------- result
    s.comment("Nothing worked: say so clearly and stop.")
    failed = s.if_nothing_saved_yet()
    youtube_failed = s.if_start(variable("Platform"), IS, "youtube")
    unavailable = s.if_start(s.match(r"content\.video\.", variable("Cobalt Errors")),
                             HAS_ANY_VALUE)
    s.alert(NAME, YOUTUBE_UNAVAILABLE)
    s.otherwise(unavailable)
    s.alert(NAME, YOUTUBE_FAILURE)
    s.end_if(unavailable)
    s.otherwise(youtube_failed)
    s.alert(NAME, FAILURE_MESSAGE)
    s.end_if(youtube_failed)
    s.stop()
    s.end_if(failed)

    s.comment("Save: videos and photos go to Photos (or to the Files folder, "
              "see Settings); anything else goes to the Files folder in "
              "iCloud Drive > Shortcuts.")
    # YouTube audio always goes to Files (it isn't a video for Photos).
    s.set_variable("Destination", s.text(variable("Save To")))
    audio_only = s.if_start(s.match(r"^youtube:Audio$", s.text(
        variable("Platform"), ":", variable("YouTube Mode"))), HAS_ANY_VALUE)
    s.set_variable("Destination", s.text("Files"))
    s.end_if(audio_only)
    loop, item = s.repeat_start(variable("Files"))
    # Through a Text action: matching on the File Extension of a WebP photo
    # straight away found nothing on macOS 27, so it went to Files.
    ext = s.text(s.file_detail(item, "File Extension"))
    to_photos = s.if_start(s.match(TO_PHOTOS, variable("Destination"), ":", ext),
                           HAS_ANY_VALUE)
    s.add_to_variable("Photo Items", item)
    if cfg.debug:
        s.log("to Photos: ", s.file_detail(item, "Name"), ".", ext, " ",
              s.file_detail(item, "File Size"))
    s.otherwise(to_photos)
    s.add_to_variable("Other Files", item)
    if cfg.debug:
        s.log("to Files/", variable("Folder"), ": ", s.file_detail(item, "Name"),
              ".", ext, " ", s.file_detail(item, "File Size"))
    s.end_if(to_photos)
    s.repeat_end(loop)

    has_photos = s.if_start(variable("Photo Items"), HAS_ANY_VALUE)
    if cfg.debug:
        s.comment("DEBUG: not saved to Photos, only listed.")
    else:
        s.save_to_photos(variable("Photo Items"))
    s.end_if(has_photos)
    # One full path per file: Save File creates missing folders on the way,
    # but a path to a folder that doesn't exist yet would save one file named
    # after the folder. A name that is taken gets "-2" (no overwrite).
    loop, item = s.repeat_start(variable("Other Files"))
    s.save_file(item, ["/", variable("Folder"), "/", s.file_detail(item, "Name"), ".",
                       s.file_detail(item, "File Extension")], overwrite=False)
    s.repeat_end(loop)

    saved = s.count(variable("Files"))
    notify = s.if_start(variable("Notify"), IS, "On")
    went_to_files = s.if_start(variable("Other Files"), HAS_ANY_VALUE)
    message = ("Saved ", saved, " item(s). Files are in iCloud Drive > Shortcuts > ",
               variable("Folder"), ".\n" + CREDIT)
    if cfg.debug:
        s.log("notification: ", *message)
    else:
        s.notification(NAME, *message)
    s.otherwise(went_to_files)
    message = ("Saved ", saved, " item(s) to your iPhone.\n" + CREDIT)
    if cfg.debug:
        s.log("notification: ", *message)
    else:
        s.notification(NAME, *message)
    s.end_if(went_to_files)
    s.end_if(notify)

    if cfg.debug:
        s.report("RESULT: saved ", saved, " item(s)")

    assert s.repeat_depth == 0
    return s.actions


def build_workflow(cfg):
    input_classes = ["WFURLContentItem", "WFStringContentItem"]
    output_classes = []
    if cfg.debug:
        # `shortcuts run --input-path` hands over a file; the report is the output.
        input_classes.append("WFGenericFileContentItem")
        output_classes = ["WFStringContentItem"]
    return {
        "WFWorkflowName": cfg.name,
        "WFWorkflowActions": build_actions(cfg),
        "WFWorkflowClientVersion": "2106.0.3",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": ICON_GLYPH_DOWNLOAD_ARROW,
            "WFWorkflowIconStartColor": ICON_COLOR_BLUE,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": input_classes,
        "WFWorkflowOutputContentItemClasses": output_classes,
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowHasOutputFallback": False,
        "WFQuickActionSurfaces": [],
    }


def check_balanced(actions):
    """Every If, Repeat and Menu must open and close in order."""
    stack = []
    for action in actions:
        params = action["WFWorkflowActionParameters"]
        if "GroupingIdentifier" not in params:
            continue
        mode = params["WFControlFlowMode"]
        group = params["GroupingIdentifier"]
        if mode == 0:
            stack.append(group)
        elif not stack or stack[-1] != group:
            raise SystemExit("control flow is not nested correctly")
        elif mode == 2:
            stack.pop()
    if stack:
        raise SystemExit("an If, Repeat or Menu is never closed")


def check_patterns():
    """The X size patterns must accept exactly the sizes up to each limit."""
    import re
    for limit in (360, 480, 720, 1080):
        small = re.compile(le_number(limit) + "$")
        for number in range(1, 5000):
            if bool(small.match(str(number))) != (number <= limit):
                raise SystemExit("le_number(%d) is wrong for %d" % (limit, number))
        pattern = re.compile(x_format_pattern(limit))
        for width, height in ((320, 320), (480, 852), (720, 1280), (1280, 720),
                              (1080, 1920), (1920, 1080), (1080, 1080)):
            link = ("https://video.twimg.com/ext_tw_video/1/pu/vid/avc1/%dx%d/a.mp4?tag=12"
                    % (width, height))
            if bool(pattern.search(link)) != (min(width, height) <= limit):
                raise SystemExit("x_format_pattern(%d) is wrong for %s" % (limit, link))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sign", action="store_true",
                        help="also sign with `shortcuts sign` (macOS only)")
    parser.add_argument("--debug", action="store_true",
                        help="build the 'SwiftDrop Debug' test copy into build/")
    args = parser.parse_args()

    check_patterns()
    cfg = Config(args.debug)
    workflow = build_workflow(cfg)
    check_balanced(workflow["WFWorkflowActions"])

    os.makedirs(os.path.dirname(cfg.unsigned), exist_ok=True)
    with open(cfg.unsigned, "wb") as handle:
        plistlib.dump(workflow, handle, fmt=plistlib.FMT_BINARY)
    print("wrote %s (%d actions)" % (cfg.unsigned, len(workflow["WFWorkflowActions"])))

    if args.sign:
        os.makedirs(os.path.dirname(cfg.signed), exist_ok=True)
        if os.path.exists(cfg.signed):
            os.remove(cfg.signed)  # `shortcuts sign` won't replace a file
        subprocess.run(["shortcuts", "sign", "--mode", "anyone",
                        "--input", cfg.unsigned, "--output", cfg.signed], check=True)
        print("signed %s" % cfg.signed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
