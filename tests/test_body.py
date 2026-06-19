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


class TestMockDevices:
    """Mock 设备测试。"""

    def test_mock_camera_open_close(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        assert c.is_operational() is False
        assert c.open() is True
        assert c.is_operational() is True
        c.close()
        assert c.is_operational() is False

    def test_mock_camera_capture(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.open()
        assert c.capture() == b"mock_frame_data"

    def test_mock_camera_set_faces(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.set_faces(["face_a", "face_b"])
        assert c._face_ids == ["face_a", "face_b"]

    def test_mock_microphone_open_close(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        assert m.is_operational() is False
        assert m.open() is True
        assert m.is_operational() is True

    def test_mock_microphone_capture(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        m.open()
        assert m.capture() == b"mock_audio_data"

    def test_mock_speaker_record_text(self):
        from xiaomei_brain.body.device.mock import MockSpeaker
        s = MockSpeaker()
        s.open()
        s.speak("hello")
        s.play("/path/to/song.mp3")
        assert s.last_spoken == "hello"
        assert s.last_played == "/path/to/song.mp3"


class TestMockSenses:
    """Mock 感官测试。"""

    def test_mock_eyes_see(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        body.register_sense(MockEyes(), MockCamera())
        body.open()
        result = body.eyes.see("描述这个画面")
        assert "mock vision" in result
        assert "安静的室内场景" in result

    def test_mock_eyes_recognize_faces(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc", "face_li"])
        body.register_sense(MockEyes(), camera)
        body.open()

        result = body.eyes.recognize_faces()
        assert len(result) == 2
        assert result[0]["face_id"] == "face_doc"

    def test_mock_ears_listen(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        mic = MockMicrophone()
        mic.set_speech("你好我是博士")
        mic.set_tone("happy")
        body.register_sense(MockEars(), mic)
        body.open()

        result = body.ears.listen("分析情绪")
        assert "mock audio" in result
        assert "博士" in result
        assert "happy" in result

    def test_mock_ears_recognize_voice(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        body.register_sense(MockEars(), MockMicrophone())
        body.open()

        assert body.ears.recognize_voice() == "voice_mock_001"

    def test_mock_throat_speak_and_play(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockSpeaker, MockThroat

        body = Body()
        speaker = MockSpeaker()
        body.register_sense(MockThroat(), speaker)
        body.open()

        body.throat.speak("hello")
        body.throat.play("/music/song.mp3")
        assert speaker.last_spoken == "hello"
        assert speaker.last_played == "/music/song.mp3"
