"""Body 身体感官层单元测试。"""
from __future__ import annotations


class TestDeviceABC:
    """Device 抽象基类测试。"""

    def test_camera_is_device(self):
        from xiaomei_brain.body.device import Camera, Device
        assert issubclass(Camera, Device)

    def test_microphone_is_device(self):
        from xiaomei_brain.body.device import Microphone, Device
        assert issubclass(Microphone, Device)

    def test_speaker_is_device(self):
        from xiaomei_brain.body.device import Speaker, Device
        assert issubclass(Speaker, Device)

    def test_camera_device_type(self):
        from xiaomei_brain.body.device import Camera
        assert Camera().device_type == "camera"

    def test_microphone_device_type(self):
        from xiaomei_brain.body.device import Microphone
        assert Microphone().device_type == "microphone"

    def test_speaker_device_type(self):
        from xiaomei_brain.body.device import Speaker
        assert Speaker().device_type == "speaker"

    def test_device_source(self):
        from xiaomei_brain.body.device import Camera
        c = Camera(source="/dev/video0")
        assert c.source == "/dev/video0"

    def test_abstract_methods_raise(self):
        from xiaomei_brain.body.device import Camera
        c = Camera()
        try:
            c.open()
            assert False, "should raise NotImplementedError"
        except NotImplementedError:
            pass

    def test_cannot_instantiate_device_abc(self):
        from xiaomei_brain.body.device import Device
        import pytest
        with pytest.raises(TypeError):
            Device()  # type: ignore[abstract]


class TestSenseABC:
    """Sense 抽象基类测试。"""

    def test_eyes_is_sense(self):
        from xiaomei_brain.body.sense import Eyes, Sense
        assert issubclass(Eyes, Sense)

    def test_ears_is_sense(self):
        from xiaomei_brain.body.sense import Ears, Sense
        assert issubclass(Ears, Sense)

    def test_throat_is_sense(self):
        from xiaomei_brain.body.sense import Throat, Sense
        assert issubclass(Throat, Sense)

    def test_eyes_name(self):
        from xiaomei_brain.body.sense import Eyes
        assert Eyes().name == "eyes"

    def test_ears_name(self):
        from xiaomei_brain.body.sense import Ears
        assert Ears().name == "ears"

    def test_throat_name(self):
        from xiaomei_brain.body.sense import Throat
        assert Throat().name == "throat"

    def test_sense_can_be_instantiated(self):
        """Sense 是具体基类，可直接实例化。"""
        from xiaomei_brain.body.sense import Sense
        s = Sense()
        assert s.name == ""
        assert s.online is False

    def test_not_available_without_device(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.is_available() is False

    def test_see_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.see() is None

    def test_recognize_faces_empty_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.recognize_faces() == []

    def test_listen_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Ears
        e = Ears()
        assert e.listen() is None
