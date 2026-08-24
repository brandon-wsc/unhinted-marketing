from cmd.api.routes.sessions import _image_interrupt_from_snapshot


def test_running_graph_next_is_not_image_interrupt() -> None:
    assert _image_interrupt_from_snapshot({}, ("brainstormer",)) is False
    assert _image_interrupt_from_snapshot({}, ()) is False
    assert _image_interrupt_from_snapshot({"awaiting_image_ok": False}, ("route_intent",)) is False


def test_parked_state_is_image_interrupt() -> None:
    assert _image_interrupt_from_snapshot({"awaiting_image_ok": True}, ("brainstormer",)) is True
    assert _image_interrupt_from_snapshot({"awaiting_image_ok": True}, ()) is True


def test_image_plan_checkpoint_is_image_interrupt() -> None:
    assert _image_interrupt_from_snapshot({}, ("executor_image_plan",)) is True
