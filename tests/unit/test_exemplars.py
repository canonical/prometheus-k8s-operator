import pytest
from scenario import Container, Context, Exec, State

from charm import PROMETHEUS_CONFIG


def test_default_config_doesnt_enable_exemplars(context: Context):
    # WHEN any event happens on prometheus with a default config

    container = Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container])
    state_out = context.run(context.on.update_status(), state)

    # THEN the feature flag for exemplars is not set
    assert "--enable-feature=exemplar-storage" not in state_out.get_container("prometheus").plan.services["prometheus"].command

    # AND THEN the config file does not contain the exemplars section
    config_path = state_out.get_container("prometheus").get_filesystem(context) / PROMETHEUS_CONFIG[1:]
    assert "exemplars" not in config_path.read_text()


def test_when_exemplars_are_enabled_feature_flag_is_set(context: Context):
    # WHEN any event happens on prometheus with exemplars set

    container = Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container], config={"max_global_exemplars_per_user": 150000})
    state_out = context.run(context.on.update_status(), state)

    # THEN the feature flag for exemplars is set
    assert "--enable-feature=exemplar-storage" in state_out.get_container("prometheus").plan.services["prometheus"].command

@pytest.mark.parametrize(
    "set_config, expected_exemplars",
    [
        (-100, 0),              # when max_global_exemplars_per_user is negative
        (0, 0),                 # when max_global_exemplars_per_user is 0
        (99_999, 100_000),      # when max_global_exemplars_per_user is between 1 and 100k
        (100_001, 100_001),     # when max_global_exemplars_per_user is above 100k
    ]
)
def test_exemplars_are_set_in_config(context: Context, set_config, expected_exemplars):
    # config_value: Union[str, int, float, bool] = set_config
    # config = {"max_global_exemplars_per_user": config_value}

    container = Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container], config={"max_global_exemplars_per_user": set_config})
    state_out = context.run(context.on.config_changed(), state)

    # THEN the config file does not contain the exemplars section
    config_path = state_out.get_container("prometheus").get_filesystem(context) / PROMETHEUS_CONFIG[1:]
    if expected_exemplars > 0:
        assert f"exemplars: {expected_exemplars}" in config_path.read_text()
    else:
        assert "exemplars" not in config_path.read_text()
