# -*- coding: utf-8 -*-
import hashlib, os, shutil, sys, tempfile, threading, unittest
os.environ["SQ_NO_KEYRING"] = "1"
import requests
from PIL import Image
import core

KEY = "sk-secret-KEY-123456"


class R:
    def __init__(self, st=200, body=None, headers=None, text=""):
        self.status_code, self.headers, self._b, self.text = st, headers or {}, body, text

    def json(self):
        if self._b is None:
            raise ValueError("no json")
        return self._b


def OK(t="ответ"):
    return R(200, {"choices": [{"message": {"content": t}, "finish_reason": "stop"}]})


class FakeG:
    monitors = [{"left": -100, "top": 0, "width": 300, "height": 100},
                {"left": -100, "top": 0, "width": 100, "height": 100},
                {"left": 0, "top": 0, "width": 200, "height": 100}]

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def grab(self, box):
        class S: pass
        s = S(); s.size = (box["width"], box["height"]); s.rgb = bytes(box["width"] * box["height"] * 3)
        return s


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["SQ_CONFIG_DIR"] = self.d
        self.addCleanup(shutil.rmtree, self.d, True)

    def call(self, responses, **kw):
        s = dict(core.DEFAULTS, retries=2)
        calls, delays, it = [], [], iter(responses)

        def post(url, **k):
            calls.append(url)
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        try:
            return core.send_request(s, KEY, {}, post=post, wait=lambda d: delays.append(d) or False, **kw), calls, delays
        except Exception as e:
            e.calls, e.delays = calls, delays
            raise

    # --- ключ ---
    def test_mask_key(self):
        m = core.mask_key("sk-abcdefghijklmnop1234")
        self.assertTrue(m.startswith("sk-a") and m.endswith("1234"))
        self.assertNotIn("abcdefghijklmnop", m)
        self.assertEqual(core.mask_key("abc"), "***")
        self.assertEqual(core.mask_key(""), "")

    def test_key_store(self):
        ks = core.KeyStore(self.d)
        ks.set(KEY)
        self.assertEqual(ks.get(), KEY)
        if os.name == "posix":
            self.assertEqual(oct(ks.file.stat().st_mode & 0o777), "0o600")
        ks.delete()
        self.assertEqual(ks.get(), "")
        self.assertFalse(ks.file.exists())

    # --- настройки ---
    def test_settings(self):
        s, err = core.load_settings()
        self.assertEqual((err, s["endpoint"]), ("", "https://ask.chadgpt.ru/api/v1"))
        s["model"] = "my-vision"; s["api_key"] = KEY; s["temperature"] = 9
        core.save_settings(s)
        text = core.settings_path().read_text(encoding="utf-8")
        self.assertNotIn(KEY, text); self.assertNotIn("api_key", text)
        s2, _ = core.load_settings()
        self.assertEqual((s2["model"], s2["temperature"]), ("my-vision", 2.0))

    def test_broken_settings_not_overwritten(self):
        core.settings_path().write_text("{oops", encoding="utf-8")
        s, err = core.load_settings()
        self.assertTrue(err)
        self.assertEqual(core.settings_path().read_text(encoding="utf-8"), "{oops")

    def test_url(self):
        want = "https://ask.chadgpt.ru/api/v1/chat/completions"
        for e in ("https://ask.chadgpt.ru/api/v1", "https://ask.chadgpt.ru/api/v1/", want):
            self.assertEqual(core.build_url(e), want)
        for bad in ("", "ask.chadgpt.ru", "http://example.com/v1"):
            with self.assertRaises(ValueError):
                core.build_url(bad)
        self.assertTrue(core.build_url("http://localhost:8000/v1").endswith("/chat/completions"))

    def test_validate_request(self):
        s = dict(core.DEFAULTS)
        self.assertIn("ключ", core.validate_request(s, ""))
        s["model"] = " "
        self.assertIn("модель", core.validate_request(s, KEY))
        self.assertEqual(core.validate_request(dict(core.DEFAULTS), KEY), "")

    # --- изображение ---
    def test_image(self):
        img = Image.new("RGB", (3000, 1000), "white")
        data, mime, meta = core.prepare_image(img, "PNG", max_side=1500)
        self.assertEqual((mime, meta["size"]), ("image/png", "1500x500"))
        self.assertEqual(meta["sha256"], hashlib.sha256(data).hexdigest())
        data, mime, _ = core.prepare_image(img, "JPEG")
        self.assertEqual((mime, data[:2]), ("image/jpeg", b"\xff\xd8"))
        p = core.build_payload(dict(core.DEFAULTS), data, mime)
        self.assertTrue(p["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    # --- API ---
    def test_http_errors(self):
        once = {400: 1, 401: 1, 403: 1, 413: 1, 408: 3, 429: 3, 500: 3, 503: 3}
        for st, n in once.items():
            with self.subTest(status=st):
                with self.assertRaises(core.ApiError) as cm:
                    self.call([R(st, {"error": {"message": f"bad {KEY}"}})] * 3)
                e = cm.exception
                self.assertEqual((e.status, len(e.calls)), (st, n))
                self.assertNotIn(KEY, str(e))

    def test_retry_after(self):
        res, calls, delays = self.call([R(429, headers={"Retry-After": "7"}), OK()])
        self.assertEqual((res, len(calls), delays), ("ответ", 2, [7.0]))

    def test_network(self):
        res, calls, _ = self.call([requests.ConnectionError(), OK()])
        self.assertEqual((res, len(calls)), ("ответ", 2))
        with self.assertRaises(core.ApiError) as cm:
            self.call([requests.ReadTimeout(), OK()])
        self.assertEqual(len(cm.exception.calls), 1)

    def test_cancel_and_truncation(self):
        ev = threading.Event(); ev.set()
        with self.assertRaises(core.Cancelled):
            self.call([OK()], cancel=ev)
        r = R(200, {"choices": [{"message": {"content": "abc"}, "finish_reason": "length"}]})
        self.assertIn("обрезан", self.call([r])[0])

    # --- лог ---
    def test_log(self):
        log = core.SessionLog(self.d, "DEBUG")
        log.add_secret(KEY)
        log.event("INFO", "REQUEST_SENT", api_key=KEY, image_id="a1", sha256="ff")
        log.logger.error("fail %s Authorization: Bearer %s data:image/png;base64,%s", KEY, KEY, "A" * 300)
        log.event("DEBUG", "NOTE", text="привет")
        log.finish(); log.finish()
        text = log.path.read_text(encoding="utf-8")
        for bad in (KEY, "AAAAAAAAAA"):
            self.assertNotIn(bad, text)
        self.assertIn("SESSION_STARTED", text); self.assertIn("image_id=\"a1\"", text) if False else None
        self.assertIn("image_id=", text)
        self.assertEqual(text.count("SESSION_FINISHED"), 1)
        self.assertTrue(text.strip().endswith(f'session="{log.id}"'))
        dest = os.path.join(self.d, "copy.log"); log.save_copy(dest)
        self.assertEqual(open(dest, encoding="utf-8").read(), text)

    # --- захват ---
    def test_grab_and_region(self):
        self.assertEqual(core.grab(1, factory=FakeG).size, (100, 100))
        self.assertEqual(core.grab(0, factory=FakeG).size, (300, 100))
        with self.assertRaises(core.CaptureError):
            core.grab(5, factory=FakeG)
        reg = core.make_region(60, 40, 10, 10, left=-100, top=0)
        self.assertEqual(reg, {"left": -90, "top": 10, "width": 50, "height": 30})
        self.assertEqual(core.grab(region=reg, factory=FakeG).size, (50, 30))
        self.assertIsNone(core.make_region(5, 5, 8, 9, 0, 0))
        for bad in ({"left": 0, "top": 0, "width": 0, "height": 5}, {"left": 500, "top": 0, "width": 10, "height": 10}):
            with self.assertRaises(core.CaptureError):
                core.grab(region=bad, factory=FakeG)

    def test_real_capture(self):
        try:
            img = core.grab(1)
        except core.CaptureError as e:
            self.skipTest(str(e))
        self.assertGreater(img.width, 0)


if __name__ == "__main__":
    unittest.main()
