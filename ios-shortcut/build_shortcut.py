#!/usr/bin/env python3
"""Build the "SwiftDrop" Apple Shortcut for iPhone.

Share a link from any app -> SwiftDrop -> the video or photos are saved on the
iPhone. The shortcut asks free third-party services for the direct media links
(the same idea as the "YAS Download" shortcut), so no computer is involved.

This script only uses the Python standard library. It writes the unsigned
workflow as a binary property list and, with --sign, signs it on a Mac:

    python3 ios-shortcut/build_shortcut.py --sign

which runs

    shortcuts sign --mode anyone --input ios-shortcut/build/SwiftDrop-unsigned.shortcut \
                   --output ios-shortcut/dist/SwiftDrop.shortcut

The service list lives in SERVICES and COBALT_SERVERS below. The same values
are written into a Dictionary and a Text action at the top of the shortcut, so
they can also be edited later on the iPhone itself.
"""

import argparse
import os
import plistlib
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
UNSIGNED_PATH = os.path.join(HERE, "build", "SwiftDrop-unsigned.shortcut")
SIGNED_PATH = os.path.join(HERE, "dist", "SwiftDrop.shortcut")

NAME = "SwiftDrop"
CREDIT = "Developed by Easin Codes"

# Endpoints of the free services, checked live on 2026-10-20.
SERVICES = [
    ("tiktok_api", "https://www.tikwm.com/api/?hd=1&url="),
    ("x_api", "https://api.fxtwitter.com/status/"),
    ("x_api_backup", "https://api.vxtwitter.com/i/status/"),
    ("instagram_api", "https://www.eeinstagram.com/videos/"),
    ("bluesky_api", "https://d.fxbsky.app"),
    ("bluesky_api_backup", "https://r.bskx.app"),
    ("video_quality", "720"),
]

# Community cobalt servers that answer API calls without a Turnstile/API key.
# Most servers on https://cobalt.directory need a key; only list ones whose
# "Turnstile" column shows a cross.
COBALT_SERVERS = [
    "https://rue-cobalt.xenon.zone/",
    "https://cobaltapi.cjs.nz/",
]

# File extensions (lowercase) used to decide what a download is.
MEDIA_EXT = (r"^(mp4|m4v|mov|webm|mkv|3gp|jpe?g|png|gif|webp|heic|heif|avif|"
             r"bmp|tiff?|mp3|m4a|aac|ogg|oga|opus|wav|flac)$")
PHOTOS_EXT = r"^(mp4|m4v|mov|jpe?g|png|gif|webp|heic|heif)$"
ERROR_EXT = r"^(html?|xhtml|json|txt|xml|rtf|rtfd|webarchive|plist)$"
DIRECT_FILE_TYPE = (r"^(?!.*mpegurl)((video|image|audio)/|application/(pdf|zip|"
                    r"octet-stream|x-zip-compressed|x-rar-compressed|vnd\.rar|"
                    r"x-7z-compressed|gzip|x-gzip|x-tar|epub\+zip|"
                    r"vnd\.android\.package-archive|x-apple-diskimage))")
# A file size such as "742 KB" contains a non-zero digit (Western, Arabic,
# Persian, Devanagari or Bengali); "Zero KB" or "0 bytes" does not.
NONZERO_DIGIT = "[1-9\u0661-\u0669\u06f1-\u06f9\u0967-\u096f\u09e7-\u09ef]"

# Platform detection on the full shared URL. The X, Instagram and Bluesky
# patterns also capture the post id used by the dedicated services.
X_LINK = (r"(?:^|[/.])(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx)\.com/"
          r"[^/?#]+/status(?:es)?/(\d+)")
TIKTOK_LINK = r"(?:^|[/.])tiktok\.com/"
INSTAGRAM_LINK = (r"(?:^|[/.])(?:instagram\.com|instagr\.am)/(?:[A-Za-z0-9_.]+/)?"
                  r"(?:p|reels?|tv)/([A-Za-z0-9_-]+)")
BLUESKY_LINK = r"(?:^|[/.])bsky\.app/profile/([^/?#]+)/post/([A-Za-z0-9]+)"
COBALT_LINK = (r"(?:^|[/.])(?:youtube\.com|youtu\.be|facebook\.com|fb\.watch|"
               r"pinterest\.[a-z.]+|pin\.it|twitch\.tv|vimeo\.com|reddit\.com|"
               r"redd\.it|soundcloud\.com|tumblr\.com|snapchat\.com|"
               r"dailymotion\.com|dai\.ly|streamable\.com|bilibili\.com|b23\.tv|"
               r"loom\.com|ok\.ru|vk\.com|vkvideo\.ru|rutube\.ru|"
               r"newgrounds\.com|threads\.(?:net|com))/")

FAILURE_MESSAGE = ("Couldn't download this link. The free download services may "
                   "be down or don't support this site. Try again later.")

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
    def __init__(self):
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
        self.add("conditional", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                 "UUID": new_uuid()})

    def repeat_start(self, ref):
        """Start Repeat with Each; returns (group, Repeat Item reference)."""
        group = new_uuid()
        self.add("repeat.each", {"GroupingIdentifier": group, "WFControlFlowMode": 0,
                                 "WFInput": attachment(ref)})
        self.repeat_depth += 1
        name = "Repeat Item" if self.repeat_depth == 1 else "Repeat Item %d" % self.repeat_depth
        return group, variable(name)

    def repeat_end(self, group):
        self.repeat_depth -= 1
        self.add("repeat.each", {"GroupingIdentifier": group, "WFControlFlowMode": 2,
                                 "UUID": new_uuid()})

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

    # -- actions -----------------------------------------------------------
    def comment(self, text):
        self.add("comment", {"WFCommentActionText": text})

    def text(self, *parts):
        return self.add("gettext", {"WFTextActionText": text_field(*parts)}, "Text")

    def set_variable(self, name, ref):
        self.add("setvariable", {"WFVariableName": name, "WFInput": attachment(ref)})

    def add_to_variable(self, name, ref):
        self.add("appendvariable", {"WFVariableName": name, "WFInput": attachment(ref)})

    def get_urls(self, ref):
        return self.add("detect.link", {"WFInput": text_field(ref)}, "URLs")

    def first_item(self, ref):
        return self.add("getitemfromlist", {"WFItemSpecifier": "First Item",
                                            "WFInput": attachment(ref)}, "Item from List")

    def get_clipboard(self):
        return self.add("getclipboard", {}, "Clipboard")

    def ask_text(self, prompt, default_ref):
        return self.add("ask", {"WFAskActionPrompt": prompt, "WFInputType": "Text",
                                "WFAskActionDefaultAnswer": text_field(default_ref)},
                        "Provided Input")

    def alert(self, title, message):
        self.add("alert", {"WFAlertActionTitle": text_field(title),
                           "WFAlertActionMessage": text_field(message),
                           "WFAlertActionCancelButtonShown": False})

    def stop(self):
        self.add("exit", {})

    def dictionary(self, pairs):
        return self.add("dictionary", {"WFItems": dictionary_field(pairs)}, "Dictionary")

    def dictionary_value(self, ref, key):
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

    def save_file(self, ref):
        self.add("documentpicker.save", {"WFInput": attachment(ref),
                                         "WFAskWhereToSave": True})

    def count(self, ref):
        # Apple saves this action's input as "Input"; newer builds also read WFInput.
        return self.add("count", {"WFCountType": "Items", "Input": attachment(ref),
                                  "WFInput": attachment(ref)}, "Count")

    def notification(self, title, *body_parts):
        self.add("notification", {"WFNotificationActionTitle": text_field(title),
                                  "WFNotificationActionBody": text_field(*body_parts),
                                  "WFNotificationActionSound": True})

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

    def download_media(self, url_parts, fallback_name=None, check_size=False):
        """Download one URL and add it to "Files" only if it is real media.

        A download that is a web page or JSON error is dropped, so the next
        service in the chain still gets a turn. fallback_name renames files
        whose type Shortcuts couldn't tell (for example cobalt's tunnels,
        which send a file name but no Content-Type).
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
        is_media = self.if_start(self.match(MEDIA_EXT, ext), HAS_ANY_VALUE)
        self.add_to_variable("Files", file_ref)
        if fallback_name is not None:
            self.otherwise(is_media)
            is_error = self.if_start(self.match(ERROR_EXT, ext), HAS_NO_VALUE)
            renamed = self.set_name(file_ref, *fallback_name)
            self.add_to_variable("Files", renamed)
            self.end_if(is_error)
        self.end_if(is_media)
        if size_ok is not None:
            self.end_if(size_ok)
        self.end_if(got_file)


def build_actions():
    s = Shortcut()

    # ------------------------------------------------------------------ intro
    s.comment(
        "SwiftDrop for iPhone\n" + CREDIT + "\n\n"
        "Share a link from TikTok, Instagram, YouTube, X, Facebook, Pinterest, "
        "Bluesky, Vimeo or Twitch to SwiftDrop. Videos and photos are saved to "
        "Photos; other files (audio, zip, pdf) go to Files.\n\n"
        "Privacy: the link you share is sent to free third-party download "
        "services (tikwm.com, fxtwitter.com, vxtwitter.com, eeinstagram.com, "
        "fxbsky.app, bskx.app and the cobalt servers below). They see the link "
        "and can stop working at any time.")

    # --------------------------------------------------------------- settings
    s.comment(
        "SETTINGS: the services SwiftDrop asks for the real media link. "
        "If one stops working, replace its address here.\n"
        "video_quality is used for YouTube and other cobalt sites "
        "(360, 480, 720, 1080).")
    settings = s.dictionary(SERVICES)
    s.set_variable("Settings", settings)

    s.comment(
        "Cobalt servers, one per line, tried in order. Only servers that "
        "don't need a Turnstile check or API key work here. Find more at "
        "cobalt.directory (Turnstile column shows a cross).")
    servers_text = s.text("\n".join(COBALT_SERVERS))
    s.set_variable("Cobalt Servers", s.split_lines(servers_text))

    # ------------------------------------------------------------------ input
    s.comment("Find the link: from the share sheet, or ask (the clipboard is "
              "filled in) when SwiftDrop is run on its own.")
    s.set_variable("Link", s.first_item(s.get_urls(SHORTCUT_INPUT)))
    no_link = s.if_start(variable("Link"), HAS_NO_VALUE)
    clipboard = s.get_clipboard()
    answer = s.ask_text("Paste the link to download", clipboard)
    s.set_variable("Link", s.first_item(s.get_urls(answer)))
    s.end_if(no_link)

    still_no_link = s.if_start(variable("Link"), HAS_NO_VALUE)
    s.alert(NAME, "No link found. Share a link to SwiftDrop, or copy one and run SwiftDrop again.")
    s.stop()
    s.end_if(still_no_link)

    # --------------------------------------------------------------- platform
    s.comment("Work out which site the link is from.")
    s.set_variable("Platform", s.text("other"))
    platform_matches = {}
    for name, pattern in (("x", X_LINK), ("tiktok", TIKTOK_LINK),
                          ("instagram", INSTAGRAM_LINK), ("bluesky", BLUESKY_LINK),
                          ("cobalt", COBALT_LINK)):
        matches = s.match(pattern, variable("Link"))
        platform_matches[name] = matches
        found = s.if_start(matches, HAS_ANY_VALUE)
        s.set_variable("Platform", s.text(name))
        s.end_if(found)

    # ----------------------------------------------------------------- TikTok
    s.comment("TikTok: tikwm.com gives the video without watermark, or every "
              "photo of a slideshow.")
    is_tiktok = s.if_start(variable("Platform"), IS, "tiktok")
    encoded = s.url_encode(variable("Link"))
    api = s.dictionary_value(variable("Settings"), "tiktok_api")
    reply = s.get_dictionary(s.get_contents([api, encoded]))
    images = s.dictionary_value(reply, "data.images")
    has_images = s.if_has_items(images)
    loop, item = s.repeat_start(images)
    s.download_media([item], fallback_name=("TikTok photo.jpg",))
    s.repeat_end(loop)
    s.otherwise(has_images)
    hd_video = s.dictionary_value(reply, "data.hdplay")
    has_hd = s.if_has_items(hd_video)
    s.download_media([hd_video], fallback_name=("TikTok video.mp4",))
    s.end_if(has_hd)
    retry = s.if_nothing_saved_yet()
    video = s.dictionary_value(reply, "data.play")
    has_video = s.if_has_items(video)
    s.download_media([video], fallback_name=("TikTok video.mp4",))
    s.end_if(has_video)
    s.end_if(retry)
    s.end_if(has_images)
    s.end_if(is_tiktok)

    # ---------------------------------------------------------------------- X
    s.comment("X / Twitter: FixTweet (fxtwitter) lists every video, GIF and "
              "photo of the post; vxtwitter is the backup.")
    is_x = s.if_start(variable("Platform"), IS, "x")
    post_id = s.match_group(platform_matches["x"], 1)
    api = s.dictionary_value(variable("Settings"), "x_api")
    reply = s.get_dictionary(s.get_contents([api, post_id]))
    media = s.dictionary_value(reply, "tweet.media.all")
    has_media = s.if_has_items(media)
    loop, item = s.repeat_start(media)
    s.download_media([s.dictionary_value(item, "url")])
    s.repeat_end(loop)
    s.end_if(has_media)

    backup = s.if_nothing_saved_yet()
    api = s.dictionary_value(variable("Settings"), "x_api_backup")
    reply = s.get_dictionary(s.get_contents([api, post_id]))
    media = s.dictionary_value(reply, "mediaURLs")
    has_media = s.if_has_items(media)
    loop, item = s.repeat_start(media)
    s.download_media([item])
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
        api = s.dictionary_value(variable("Settings"), key)
        s.download_media([api, "/profile/", handle, "/post/", post])
        s.end_if(not_yet)
    s.end_if(is_bluesky)

    # -------------------------------------------------------------- Instagram
    s.comment("Instagram: InstaFix (eeinstagram.com) sends each photo or video "
              "of the post in turn (1, 2, 3...) until there are no more. Its "
              "links work in Shortcuts, unlike some long Instagram links that "
              "Shortcuts cuts short.")
    is_instagram = s.if_start(variable("Platform"), IS, "instagram")
    code = s.match_group(platform_matches["instagram"], 1)
    api = s.dictionary_value(variable("Settings"), "instagram_api")
    loop, index = s.repeat_times_start(20)
    more = s.if_start(variable("Instagram Done"), HAS_NO_VALUE)
    item = s.add("downloadurl", {"WFURL": text_field(api, code, "/", index),
                                 "WFHTTPMethod": "GET"}, "Contents of URL")
    got_item = s.if_start(item, HAS_ANY_VALUE)
    ext = s.file_detail(item, "File Extension")
    is_media = s.if_start(s.match(MEDIA_EXT, ext), HAS_ANY_VALUE)
    s.add_to_variable("Files", item)
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
    s.end_if(is_file)
    s.end_if(is_other)

    # ----------------------------------------------------------------- cobalt
    s.comment("cobalt servers: YouTube, Facebook, Pinterest, Twitch, Vimeo "
              "and the rest, and the backup for every site above. "
              "Each server is tried in turn until something is saved.")
    nothing_yet = s.if_nothing_saved_yet()
    quality = s.dictionary_value(variable("Settings"), "video_quality")
    loop, server = s.repeat_start(variable("Cobalt Servers"))
    not_yet = s.if_nothing_saved_yet()
    reply = s.get_contents(
        [server],
        headers=[("Accept", "application/json"), ("Content-Type", "application/json")],
        json_body=[("url", (variable("Link"),)), ("videoQuality", (quality,)),
                   ("youtubeVideoCodec", "h264")])
    reply = s.get_dictionary(reply)
    single = s.dictionary_value(reply, "url")
    has_single = s.if_has_items(single)
    filename = s.dictionary_value(reply, "filename")
    s.download_media([single], fallback_name=(filename,), check_size=True)
    s.otherwise(has_single)
    picker = s.dictionary_value(reply, "picker")
    has_picker = s.if_has_items(picker)
    inner, choice = s.repeat_start(picker)
    s.download_media([s.dictionary_value(choice, "url")])
    s.repeat_end(inner)
    s.end_if(has_picker)
    s.end_if(has_single)
    s.end_if(not_yet)
    s.repeat_end(loop)
    s.end_if(nothing_yet)

    # ----------------------------------------------------------------- result
    s.comment("Nothing worked: say so clearly and stop.")
    failed = s.if_nothing_saved_yet()
    s.alert(NAME, FAILURE_MESSAGE)
    s.stop()
    s.end_if(failed)

    s.comment("Save: videos and photos go to Photos, anything else to Files.")
    loop, item = s.repeat_start(variable("Files"))
    ext = s.file_detail(item, "File Extension")
    to_photos = s.if_start(s.match(PHOTOS_EXT, ext), HAS_ANY_VALUE)
    s.add_to_variable("Photo Items", item)
    s.otherwise(to_photos)
    s.add_to_variable("Other Files", item)
    s.end_if(to_photos)
    s.repeat_end(loop)

    has_photos = s.if_start(variable("Photo Items"), HAS_ANY_VALUE)
    s.save_to_photos(variable("Photo Items"))
    s.end_if(has_photos)
    has_files = s.if_start(variable("Other Files"), HAS_ANY_VALUE)
    s.save_file(variable("Other Files"))
    s.end_if(has_files)

    saved = s.count(variable("Files"))
    s.notification(NAME, "Saved ", saved, " item(s) to your iPhone.\n" + CREDIT)

    assert s.repeat_depth == 0
    return s.actions


def build_workflow():
    return {
        "WFWorkflowName": NAME,
        "WFWorkflowActions": build_actions(),
        "WFWorkflowClientVersion": "2106.0.3",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": ICON_GLYPH_DOWNLOAD_ARROW,
            "WFWorkflowIconStartColor": ICON_COLOR_BLUE,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": ["WFURLContentItem", "WFStringContentItem"],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowHasOutputFallback": False,
        "WFQuickActionSurfaces": [],
    }


def check_balanced(actions):
    """Every If and Repeat must open and close in order."""
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
        raise SystemExit("an If or Repeat is never closed")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sign", action="store_true",
                        help="also sign with `shortcuts sign` (macOS only)")
    args = parser.parse_args()

    workflow = build_workflow()
    check_balanced(workflow["WFWorkflowActions"])

    os.makedirs(os.path.dirname(UNSIGNED_PATH), exist_ok=True)
    with open(UNSIGNED_PATH, "wb") as handle:
        plistlib.dump(workflow, handle, fmt=plistlib.FMT_BINARY)
    print("wrote %s (%d actions)" % (UNSIGNED_PATH, len(workflow["WFWorkflowActions"])))

    if args.sign:
        os.makedirs(os.path.dirname(SIGNED_PATH), exist_ok=True)
        subprocess.run(["shortcuts", "sign", "--mode", "anyone",
                        "--input", UNSIGNED_PATH, "--output", SIGNED_PATH], check=True)
        print("signed %s" % SIGNED_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
