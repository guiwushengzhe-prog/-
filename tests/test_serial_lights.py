import json
from collections import deque
import unittest
from unittest.mock import patch

from piano.serial_lights import SerialLights


class Receiver:
    def __init__(self, protocol=2):
        self.is_open = True
        self.protocol = protocol
        self.sent = []
        self.replies = deque()
        self.drop = False
        self.error = None
        self.fragment = False
        self.sequence = 0

    def write(self, data):
        request = json.loads(data)
        self.sent.append(request)
        if self.protocol == 1 or self.drop:
            return len(data)
        sequence, kind = request.get("seq", 0), request["type"]
        if kind == "hello":
            reply = {"type": "hello", "seq": sequence, "protocol": 2, "firmware": "2.0.0", "led_count": 60}
        elif self.error:
            reply = {"type": "error", "seq": sequence, "code": self.error}
        else:
            reply = {"type": "ack", "seq": sequence, "command": kind}
        message = json.dumps(reply).encode() + b"\n"
        if self.fragment:
            self.replies.extend([message[:8], message[8:]])
        else:
            self.replies.append(message)
        return len(data)

    def read_until(self, delimiter, size):
        return self.replies.popleft() if self.replies else b""

    def close(self):
        self.is_open = False


class SerialLightsTests(unittest.TestCase):
    def connected(self):
        port = Receiver()
        controller = SerialLights()
        with patch.object(controller, "ports", return_value=[{"device": "COM15"}]), \
                patch("serial.Serial", return_value=port):
            status = controller.connect("COM15", 115200)
        self.assertTrue(status["verified"])
        self.assertEqual(status["led_count"], 60)
        self.assertEqual(port.sent[-1]["type"], "clear")
        return controller, port

    def test_identify_confirm_then_ping_without_repainting(self):
        controller, port = self.connected()
        request = {"pixels": [[12, 255, 0, 0]], "brightness": .9}
        result = controller.frame(request)
        self.assertTrue(result["verified"])
        self.assertEqual(result["last_ack"]["command"], "frame")
        self.assertEqual(port.sent[-1]["brightness"], .9)
        controller.frame(request)
        self.assertEqual(port.sent[-1]["type"], "ping")
        self.assertNotIn("pixels", port.sent[-1])
        controller.frame({"pixels": [], "brightness": .15})
        self.assertEqual(port.sent[-1]["type"], "clear")
        controller.disconnect()
        self.assertFalse(port.is_open)

    def test_partial_and_stale_replies_do_not_acknowledge_wrong_frame(self):
        controller, port = self.connected()
        port.fragment = True
        port.replies.append(b'{"type":"ack","seq":1,"command":"frame"}\n')
        result = controller.frame({"pixels": [[0, 10, 20, 30]]})
        self.assertGreater(result["last_ack"]["sequence"], 1)
        self.assertEqual(result["last_ack"]["command"], "frame")

    def test_firmware_range_rejection_does_not_disconnect_good_port(self):
        controller, port = self.connected()
        before = len(port.sent)
        with self.assertRaisesRegex(ValueError, "60"):
            controller.frame({"pixels": [[60, 255, 0, 0]]})
        self.assertEqual(len(port.sent), before)
        self.assertTrue(port.is_open)
        port.error = "pixels"
        with self.assertRaisesRegex(ValueError, "固件范围"):
            controller.frame({"pixels": [[0, 255, 0, 0]]})
        self.assertTrue(port.is_open)

    def test_silent_or_restarted_receiver_is_not_reported_as_applied(self):
        controller, port = self.connected()
        port.replies.append(b'{"type":"ready","seq":0,"protocol":2}\n')
        with self.assertRaisesRegex(OSError, "重启"):
            controller.frame({"pixels": [[0, 255, 0, 0]]})
        self.assertFalse(port.is_open)
        controller, port = self.connected()
        port.drop = True
        with self.assertRaisesRegex(OSError, "没有确认"):
            controller.frame({"pixels": [[0, 255, 0, 0]]})
        self.assertFalse(controller.status()["connected"])

    def test_legacy_firmware_is_usable_but_explicitly_unverified(self):
        controller, port = SerialLights(), Receiver(protocol=1)
        clock = iter(i * .11 for i in range(100))
        with patch.object(controller, "ports", return_value=[{"device": "COM15"}]), \
                patch("serial.Serial", return_value=port), \
                patch("piano.serial_lights.time.monotonic", side_effect=lambda: next(clock)):
            result = controller.connect("COM15", 115200)
        self.assertFalse(result["verified"])
        self.assertEqual(result["protocol"], 1)
        self.assertFalse(controller.frame({"pixels": [[0, 255, 0, 0]]})["verified"])
        self.assertEqual(port.sent[-1]["type"], "frame")


if __name__ == "__main__":
    unittest.main()
