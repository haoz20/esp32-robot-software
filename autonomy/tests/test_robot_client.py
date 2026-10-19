from unittest.mock import patch

from autonomy.robot_client import RobotClient


@patch("autonomy.robot_client.requests.Session")
def test_go_calls_the_go_endpoint(mock_session_cls):
    mock_session = mock_session_cls.return_value
    client = RobotClient("192.168.4.1", port=80, timeout_s=2.0)
    client.go()
    mock_session.get.assert_called_once_with("http://192.168.4.1:80/go", timeout=2.0)


@patch("autonomy.robot_client.requests.Session")
def test_stop_calls_the_stop_endpoint(mock_session_cls):
    mock_session = mock_session_cls.return_value
    client = RobotClient("192.168.4.1")
    client.stop()
    mock_session.get.assert_called_once_with("http://192.168.4.1:80/stop", timeout=2.0)


@patch("autonomy.robot_client.requests.Session")
def test_left_and_right_call_distinct_endpoints(mock_session_cls):
    mock_session = mock_session_cls.return_value
    client = RobotClient("192.168.4.1")
    client.left()
    client.right()
    assert mock_session.get.call_args_list[0].args == ("http://192.168.4.1:80/left",)
    assert mock_session.get.call_args_list[1].args == ("http://192.168.4.1:80/right",)


@patch("autonomy.robot_client.requests.Session")
def test_back_calls_the_back_endpoint(mock_session_cls):
    mock_session = mock_session_cls.return_value
    client = RobotClient("192.168.4.1")
    client.back()
    mock_session.get.assert_called_once_with("http://192.168.4.1:80/back", timeout=2.0)


@patch("autonomy.robot_client.requests.Session")
def test_reuses_a_single_session_across_calls(mock_session_cls):
    client = RobotClient("192.168.4.1")
    client.go()
    client.stop()
    client.left()
    assert mock_session_cls.call_count == 1
