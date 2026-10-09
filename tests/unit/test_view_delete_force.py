"""Unit tests for VMS View resource delete force-retry (opt-in)."""

from unittest.mock import MagicMock

import pytest
from requests.exceptions import HTTPError

from vast_csi.session.resources import View


def _http_error(status_code: int, text: str) -> HTTPError:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return HTTPError(response=response)


@pytest.mark.parametrize(
    "root_export, bucket_name, expected",
    [
        ("/cosi", "b1", "/cosi/b1"),
        ("cosi/", "b1", "/cosi/b1"),
        ("", "b1", "/b1"),
        (None, "b1", "/b1"),
        ("  /cosi/nested/  ", "b1", "/cosi/nested/b1"),
    ],
)
def test_view_bucket_path(root_export, bucket_name, expected):
    assert View.bucket_path(root_export, bucket_name) == expected


def test_view_delete_by_id_retries_force_on_not_empty_409_when_opted_in():
    session = MagicMock()
    views = View(session)
    session.delete.side_effect = [
        _http_error(409, '{"detail":"You cannot delete this bucket as it is not empty."}'),
        None,
    ]

    views.delete_by_id(42, force_if_not_empty=True)

    assert session.delete.call_count == 2
    assert session.delete.call_args_list[0].args[0] == "views/42"
    assert session.delete.call_args_list[0].kwargs.get("params") is None
    assert session.delete.call_args_list[1].kwargs.get("params") == {"force": True}


def test_view_delete_by_id_default_does_not_force_on_not_empty_409():
    session = MagicMock()
    views = View(session)
    session.delete.side_effect = _http_error(
        409, '{"detail":"You cannot delete this bucket as it is not empty."}'
    )

    with pytest.raises(HTTPError):
        views.delete_by_id(42)

    session.delete.assert_called_once()
    assert session.delete.call_args.kwargs.get("params") is None


def test_ensure_creates_path_export_without_alias():
    session = MagicMock()
    session.viewpolicies.one.return_value = MagicMock(id=1, tenant_id=1)
    session.post.return_value = MagicMock(id=7, path="/k8s", protocols=["NFS4"])
    views = View(session)
    views.one = MagicMock(return_value=None)

    view = views.ensure("/k8s", protocols=["NFS4"], view_policy="del-pol", qos_policy=None)

    assert view.id == 7
    payload = session.post.call_args.kwargs["data"]
    assert payload["path"] == "/k8s"
    assert payload["protocols"] == ["NFS4"]
    assert "alias" not in payload
    session.delete.assert_not_called()


def test_ensure_returns_existing_view_unchanged():
    session = MagicMock()
    existing = MagicMock(id=7, path="/k8s", protocols=["NFS"])
    views = View(session)
    views.one = MagicMock(return_value=existing)

    view = views.ensure("/k8s", protocols=["NFS4"], view_policy="del-pol", qos_policy=None)

    assert view is existing
    session.post.assert_not_called()
    session.patch.assert_not_called()
    session.delete.assert_not_called()


def test_view_delete_by_id_does_not_force_on_other_errors():
    session = MagicMock()
    views = View(session)
    session.delete.side_effect = _http_error(409, '{"detail":"other conflict"}')

    with pytest.raises(HTTPError):
        views.delete_by_id(42, force_if_not_empty=True)

    session.delete.assert_called_once()
    assert session.delete.call_args.kwargs.get("params") is None
