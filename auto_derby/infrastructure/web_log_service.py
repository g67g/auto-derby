# -*- coding=UTF-8 -*-
# pyright: strict

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import threading
import webbrowser
from datetime import datetime
from typing import Any, Dict, Optional, Text

import PIL.Image

from .. import imagetools, web
from ..log import Image, Level, Service
from ..web import Webview

_LOGGER = logging.getLogger(__name__)


class _DefaultWebview(Webview):
    def open(self, url: Text) -> None:
        webbrowser.open(url)

    def shutdown(self) -> None:
        pass


def _image_data_url(img: PIL.Image.Image) -> Text:
    b = io.BytesIO()
    img.save(b, "PNG")
    data = base64.b64encode(b.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{data}"


class WebLogService(Service):
    default_webview: Webview = _DefaultWebview()
    default_port = 8400
    default_host = "127.0.0.1"
    default_buffer_path = ""
    default_image_path = ""

    def __init__(
        self,
        host: Optional[Text] = None,
        port: Optional[int] = None,
        webview: Optional[web.Webview] = None,
        buffer_path: Optional[Text] = None,
        image_path: Optional[Text] = None,
    ) -> None:
        if host is None:
            host = self.default_host
        if port is None:
            port = self.default_port
        if webview is None:
            webview = self.default_webview
        if buffer_path is None:
            buffer_path = self.default_buffer_path
        if image_path is None:
            image_path = self.default_image_path
        self.image_path = image_path

        self._s = web.Stream(buffer_path, "text/plain; charset=utf-8")

        httpd = web.create_server(
            (host, port),
            web.Blob(
                web.page.render(
                    {
                        "type": "LOG",
                        "streamURL": "/log",
                    }
                ).encode("utf-8"),
                "text/html; charset=utf-8",
            ),
            web.page.ASSETS,
            web.Path("/log", self._s),
            web.Route("/images/", web.Dir(self.image_path)),
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        host, port = httpd.server_address
        url = f"http://{host}:{port}"
        _LOGGER.info("web log service start at:\t%s", url)
        webview.open(url)

    def __del__(self):
        self._s.close()

    def _line(self, fields: Dict[Text, Any]):
        data = json.dumps(
            {
                "ts": datetime.now().astimezone().isoformat(),
                "lv": fields["lv"],
                "t": fields["t"],
                **fields,
            }
        ).encode("utf-8")
        self._s.write(data)
        self._s.write(b"\n")

    def _text(self, level: Level, msg: Text):
        self._line({"t": "TEXT", "lv": level.value, "msg": msg})

    def _image(self, level: Level, caption: Text, url: Text):
        self._line({"t": "IMAGE", "lv": level.value, "caption": caption, "url": url})

    def text(self, msg: Text, /, *, level: Level = Level.INFO):
        self._text(level, msg)

    def image(self, caption: Text, image: Image, /, *, level: Level = Level.INFO):

        if isinstance(image, PIL.Image.Image):
            pil_img = image
        else:
            pil_img = imagetools.pil_image(image)

        n_pixels = pil_img.width * pil_img.height
        if n_pixels < 400 * 200:
            url = _image_data_url(pil_img)
            self._image(level, caption, url)
            return
        if not self.image_path:
            self._text(
                level,
                "%s w=%d h=%d (not record large image unless WebLogService.image_path set)"
                % (caption, pil_img.width, pil_img.height),
            )
            return

        h = hashlib.md5(pil_img.tobytes()).hexdigest()
        pathname = f"{h[0]}/{h[1:3]}/{h[3:]}.png"
        dst = os.path.join(self.image_path, pathname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        pil_img.save(dst)
        url = "/images/" + pathname
        self._image(level, caption, url)
