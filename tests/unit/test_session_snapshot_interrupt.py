from cmd.api.routes.sessions import _parked_node_from_snapshot


def test_running_graph_next_is_not_image_interrupt() -> None:
    assert _parked_node_from_snapshot({}, ("brainstormer",)) is None
    assert _parked_node_from_snapshot({}, ()) is None
    assert (
        _parked_node_from_snapshot({"awaiting_image_ok": False}, ("route_intent",))
        is None
    )


def test_parked_state_is_image_interrupt() -> None:
    assert (
        _parked_node_from_snapshot({"awaiting_image_ok": True}, ("brainstormer",))
        == "executor_image_gen"
    )
    assert (
        _parked_node_from_snapshot({"awaiting_image_ok": True}, ())
        == "executor_image_gen"
    )


def test_image_gen_checkpoint_is_image_interrupt() -> None:
    assert (
        _parked_node_from_snapshot({}, ("executor_image_gen",))
        == "executor_image_gen"
    )
    assert _parked_node_from_snapshot({}, ("executor_image_plan",)) is None


def test_parked_state_is_angle_interrupt() -> None:
    assert (
        _parked_node_from_snapshot({"awaiting_angle_pick": True}, ())
        == "angle_gate"
    )
    assert _parked_node_from_snapshot({}, ("angle_gate",)) == "angle_gate"


def test_image_flag_wins_over_angle_checkpoint() -> None:
    # Flags are authoritative; snap.next alone cannot distinguish parks.
    assert (
        _parked_node_from_snapshot(
            {"awaiting_image_ok": True, "awaiting_angle_pick": True},
            ("angle_gate",),
        )
        == "executor_image_gen"
    )
