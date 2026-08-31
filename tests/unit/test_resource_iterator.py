"""Tests for ResourceIterator pagination functionality."""
import pytest
from unittest.mock import MagicMock, patch
from easypy.bunch import Bunch
from vast_csi.session import ResourceIterator, VastResource
from vast_csi.session.resources import View


class TestResourceIterator:
    """Test suite for ResourceIterator class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock VmsSession."""
        session = MagicMock()
        session.request = MagicMock()
        session.get = MagicMock()
        return session

    @pytest.fixture
    def mock_resource(self, mock_session):
        """Create a mock VastResource."""
        resource = MagicMock(spec=VastResource)
        resource.session = mock_session
        resource.resource_name = "views"
        return resource

    def test_iterator_non_paginated_list(self, mock_resource, mock_session):
        """Test iterator with non-paginated list response."""
        # Setup mock to return a plain list
        mock_session.get.return_value = [
            Bunch(id=1, name="view1"),
            Bunch(id=2, name="view2"),
            Bunch(id=3, name="view3"),
        ]

        iterator = ResourceIterator(resource=mock_resource, initial_params={"tenant_id": 1})
        
        # First call to next() should initialize and return results
        results = iterator.next()
        assert len(results) == 3
        assert results[0].name == "view1"
        assert iterator.count() == 3
        assert not iterator.has_next()

    def test_iterator_paginated_response(self, mock_resource, mock_session):
        """Test iterator with paginated response."""
        # Setup mock to return paginated response
        page1 = Bunch(
            results=[Bunch(id=1, name="view1"), Bunch(id=2, name="view2")],
            count=5,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=3, name="view3"), Bunch(id=4, name="view4")],
            count=5,
            next="https://vms.example.com/api/v1/views/?page=3",
            previous="https://vms.example.com/api/v1/views/?page=1"
        )
        page3 = Bunch(
            results=[Bunch(id=5, name="view5")],
            count=5,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=2"
        )

        mock_session.get.return_value = page1
        mock_session.request.side_effect = [page2, page3]

        iterator = ResourceIterator(resource=mock_resource, page_size=2)
        
        # First page
        results1 = iterator.next()
        assert len(results1) == 2
        assert results1[0].name == "view1"
        assert iterator.count() == 5
        assert iterator.has_next()
        
        # Second page
        results2 = iterator.next()
        assert len(results2) == 2
        assert results2[0].name == "view3"
        assert iterator.has_next()
        assert iterator.has_previous()
        
        # Third page
        results3 = iterator.next()
        assert len(results3) == 1
        assert results3[0].name == "view5"
        assert not iterator.has_next()

    def test_iterator_all_method(self, mock_resource, mock_session):
        """Test iterator.all() method fetches all pages."""
        # Setup mock to return paginated response
        page1 = Bunch(
            results=[Bunch(id=1, name="view1"), Bunch(id=2, name="view2")],
            count=4,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=3, name="view3"), Bunch(id=4, name="view4")],
            count=4,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=1"
        )

        mock_session.get.return_value = page1
        mock_session.request.return_value = page2

        iterator = ResourceIterator(resource=mock_resource, page_size=2)
        
        # Fetch all results at once
        all_results = iterator.all()
        assert len(all_results) == 4
        assert all_results[0].name == "view1"
        assert all_results[3].name == "view4"

    def test_iterator_reset(self, mock_resource, mock_session):
        """Test iterator.reset() method."""
        # Setup mock to return paginated response
        page1 = Bunch(
            results=[Bunch(id=1, name="view1")],
            count=2,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=2, name="view2")],
            count=2,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=1"
        )

        mock_session.get.return_value = page1
        mock_session.request.return_value = page2

        iterator = ResourceIterator(resource=mock_resource)
        
        # Fetch first page
        results1 = iterator.next()
        assert results1[0].name == "view1"
        
        # Fetch second page
        results2 = iterator.next()
        assert results2[0].name == "view2"
        assert not iterator.has_next()
        
        # Reset and fetch again
        mock_session.get.return_value = page1
        results_reset = iterator.reset()
        assert results_reset[0].name == "view1"
        assert iterator.has_next()

    def test_iterator_empty_response(self, mock_resource, mock_session):
        """Test iterator with empty response."""
        mock_session.get.return_value = Bunch(
            results=[],
            count=0,
            next=None,
            previous=None
        )

        iterator = ResourceIterator(resource=mock_resource)
        
        results = iterator.next()
        assert len(results) == 0
        assert iterator.count() == 0
        assert not iterator.has_next()

    def test_iterator_page_size_parameter(self, mock_resource, mock_session):
        """Test that page_size parameter is added to initial request."""
        mock_session.get.return_value = Bunch(
            results=[Bunch(id=1, name="view1")],
            count=1,
            next=None,
            previous=None
        )

        iterator = ResourceIterator(resource=mock_resource, page_size=50)
        iterator.next()
        
        # Verify page_size was added to params
        call_args = mock_session.get.call_args
        assert call_args[1]['params']['page_size'] == 50

    def test_iterator_initial_params_preserved(self, mock_resource, mock_session):
        """Test that initial params are preserved and combined with page_size."""
        mock_session.get.return_value = Bunch(
            results=[],
            count=0,
            next=None,
            previous=None
        )

        initial_params = {"tenant_id": 1, "name__contains": "test"}
        iterator = ResourceIterator(
            resource=mock_resource, 
            initial_params=initial_params,
            page_size=100
        )
        iterator.next()
        
        # Verify both initial params and page_size are present
        call_args = mock_session.get.call_args
        params = call_args[1]['params']
        assert params['tenant_id'] == 1
        assert params['name__contains'] == "test"
        assert params['page_size'] == 100

    def test_iterator_python_protocol(self, mock_resource, mock_session):
        """Test that iterator supports Python iterator protocol."""
        page1 = Bunch(
            results=[Bunch(id=1, name="view1")],
            count=2,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=2, name="view2")],
            count=2,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=1"
        )

        mock_session.get.return_value = page1
        mock_session.request.return_value = page2

        iterator = ResourceIterator(resource=mock_resource)
        
        # Test __iter__ and __next__
        pages = list(iterator)
        assert len(pages) == 2
        assert len(pages[0]) == 1
        assert pages[0][0].name == "view1"

    def test_iterator_str_representation(self, mock_resource, mock_session):
        """Test iterator string representation."""
        mock_session.get.return_value = Bunch(
            results=[Bunch(id=1, name="view1")],
            count=1,
            next=None,
            previous=None
        )

        iterator = ResourceIterator(resource=mock_resource, page_size=10)
        
        # Before initialization
        str_repr = str(iterator)
        assert "ResourceIterator" in str_repr
        assert "initialized=False" in str_repr
        
        # After initialization
        iterator.next()
        str_repr = str(iterator)
        assert "initialized=True" in str_repr
        assert "current_records=1" in str_repr


class TestVastResourceIterMethod:
    """Test VastResource.iter() method."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock VmsSession."""
        session = MagicMock()
        session.get = MagicMock()
        return session

    def test_resource_iter_method_exists(self, mock_session):
        """Test that VastResource has iter() method."""
        from vast_csi.session import VastResource
        
        # Create a concrete subclass for testing
        class TestResource(VastResource):
            resource_name = "test"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        resource = TestResource(session=mock_session)
        assert hasattr(resource, 'iter')
        assert callable(resource.iter)

    def test_resource_iter_returns_iterator(self, mock_session):
        """Test that resource.iter() returns a ResourceIterator."""
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "test"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        resource = TestResource(session=mock_session)
        iterator = resource.iter(page_size=50, tenant_id=1)
        
        assert isinstance(iterator, ResourceIterator)
        assert iterator.page_size == 50
        assert iterator.initial_params['tenant_id'] == 1

    def test_resource_iter_integration(self, mock_session):
        """Test full integration of resource.iter().all()."""
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "views"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        # Setup paginated response
        page1 = Bunch(
            results=[Bunch(id=1, name="view1"), Bunch(id=2, name="view2")],
            count=3,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=3, name="view3")],
            count=3,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=1"
        )
        
        mock_session.get.return_value = page1
        mock_session.request.return_value = page2
        
        resource = TestResource(session=mock_session)
        
        # Fetch all results using iterator
        all_views = resource.iter(page_size=2).all()
        
        assert len(all_views) == 3
        assert all_views[0].name == "view1"
        assert all_views[2].name == "view3"

    def test_api_version_in_pagination(self, mock_session):
        """Test that API version is preserved across paginated requests."""
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "views"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        # Mock paginated response with v5 API
        page1 = Bunch({
            'results': [
                Bunch({'id': 1, 'name': 'view1'}),
                Bunch({'id': 2, 'name': 'view2'}),
            ],
            'count': 4,
            'next': 'https://vms.example.com/api/v5/views/?page=2',  # v5 in URL
            'previous': None,
        })
        
        page2 = Bunch({
            'results': [
                Bunch({'id': 3, 'name': 'view3'}),
                Bunch({'id': 4, 'name': 'view4'}),
            ],
            'count': 4,
            'next': None,
            'previous': 'https://vms.example.com/api/v5/views/?page=1',  # v5 in URL
        })
        
        call_count = {'count': 0}
        def mock_get(*args, **kwargs):
            call_count['count'] += 1
            if call_count['count'] == 1:
                # First call should be to session.get() with api_ver
                assert kwargs.get('api_ver') == 'v5'
                return page1
            else:
                # Should not reach here in this test
                raise AssertionError("Unexpected call to session.get()")
        
        def mock_request(method, path, **kwargs):
            # The iterator passes "v5/views/?page=2" to request().
            # Verify the version prefix is present in the path.
            assert 'v5' in path, f"Expected v5 in path, got: {path}"
            return page2
        
        mock_session.get = MagicMock(side_effect=mock_get)
        mock_session.request = MagicMock(side_effect=mock_request)
        
        resource = TestResource(session=mock_session)
        
        # Fetch all results with api_ver='v5'
        all_views = resource.iter(page_size=2, api_ver='v5').all()
        
        assert len(all_views) == 4
        assert all_views[0].name == "view1"
        assert all_views[3].name == "view4"
        
        # Verify session.request was called for the second page
        mock_session.request.assert_called_once()


class TestVastResourceListMethod:
    """Test VastResource.list() method."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock VmsSession."""
        session = MagicMock()
        session.get = MagicMock()
        session.request = MagicMock()
        return session

    def test_list_with_page_size_parameter(self, mock_session):
        """Test that list() can accept page_size parameter without conflicts.
        
        This test covers the bug where list(page_size=10) would cause:
        TypeError: iter() got multiple values for keyword argument 'page_size'
        """
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "snapshots"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        # Setup mock response
        mock_session.get.return_value = Bunch(
            results=[Bunch(id=1, name="snap1"), Bunch(id=2, name="snap2")],
            count=2,
            next=None,
            previous=None
        )
        
        resource = TestResource(session=mock_session)
        
        # This should not raise TypeError about multiple values for page_size
        results = resource.list(path__contains="/test", page_size=10)
        
        assert len(results) == 2
        assert results[0].name == "snap1"
        
        # Verify page_size was passed through to the API call
        call_args = mock_session.get.call_args
        assert call_args[1]['params']['page_size'] == 10
        assert call_args[1]['params']['path__contains'] == "/test"

    def test_list_without_page_size(self, mock_session):
        """Test that list() works without explicit page_size parameter."""
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "views"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        # Setup mock response
        mock_session.get.return_value = Bunch(
            results=[Bunch(id=1, name="view1")],
            count=1,
            next=None,
            previous=None
        )
        
        resource = TestResource(session=mock_session)
        
        # Call list without page_size
        results = resource.list(tenant_id=1)
        
        assert len(results) == 1
        assert results[0].name == "view1"
        
        # Verify tenant_id was passed through
        call_args = mock_session.get.call_args
        assert call_args[1]['params']['tenant_id'] == 1

    def test_list_paginated_fetches_all_pages(self, mock_session):
        """Test that list() automatically fetches all pages."""
        from vast_csi.session import VastResource
        
        class TestResource(VastResource):
            resource_name = "views"
            TARGET_STATE = "READY"
            FAILED_STATES = []
            RUNNING_STATES = []
        
        # Setup paginated response
        page1 = Bunch(
            results=[Bunch(id=1, name="view1"), Bunch(id=2, name="view2")],
            count=4,
            next="https://vms.example.com/api/v1/views/?page=2",
            previous=None
        )
        page2 = Bunch(
            results=[Bunch(id=3, name="view3"), Bunch(id=4, name="view4")],
            count=4,
            next=None,
            previous="https://vms.example.com/api/v1/views/?page=1"
        )
        
        mock_session.get.return_value = page1
        mock_session.request.return_value = page2
        
        resource = TestResource(session=mock_session)
        
        # Call list - should fetch all pages automatically
        all_results = resource.list(tenant_id=1, page_size=2)
        
        assert len(all_results) == 4
        assert all_results[0].name == "view1"
        assert all_results[3].name == "view4"


class TestIteratorForcesPaginationByDefault:
    """Verify ResourceIterator injects DEFAULT_PAGE_SIZE so VMS does not silently
    truncate large list responses (e.g. /views/ capped at 16K in VMS 5.5).

    The default applies to every VastResource (views, quotas, snapshots, ...)
    because the iterator already handles both paginated and non-paginated
    response shapes; sending page_size to an endpoint that ignores it is a no-op.
    """

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.get = MagicMock()
        session.request = MagicMock()
        return session

    def test_view_list_injects_default_page_size(self, mock_session):
        from vast_csi.session.iterator import DEFAULT_PAGE_SIZE
        # Single paginated page so .all() terminates immediately.
        mock_session.get.return_value = Bunch(
            results=[Bunch(id=1, path="/a")],
            count=1,
            next=None,
            previous=None,
        )
        view = View(session=mock_session)

        view.list(tenant_id=1)

        params = mock_session.get.call_args.kwargs.get("params", {})
        assert params.get("page_size") == DEFAULT_PAGE_SIZE
        assert params.get("tenant_id") == 1

    def test_explicit_zero_disables_pagination(self, mock_session):
        # Caller passes page_size=0 -> opt out, no page_size sent to server.
        mock_session.get.return_value = [Bunch(id=1, path="/a")]
        view = View(session=mock_session)

        view.iter(page_size=0).all()

        params = mock_session.get.call_args.kwargs.get("params", {})
        assert "page_size" not in params

    def test_view_list_respects_caller_page_size(self, mock_session):
        mock_session.get.return_value = Bunch(
            results=[], count=0, next=None, previous=None,
        )
        view = View(session=mock_session)

        view.list(path__contains="/x", page_size=10)

        params = mock_session.get.call_args.kwargs.get("params", {})
        assert params.get("page_size") == 10

    def test_iter_walks_all_pages_with_default_page_size(self, mock_session):
        from vast_csi.session.iterator import DEFAULT_PAGE_SIZE
        page1 = Bunch(
            results=[Bunch(id=i) for i in range(1, 3)],
            count=4,
            next="https://vms.example.com/api/v5/views/?page=2&page_size=1000",
            previous=None,
        )
        page2 = Bunch(
            results=[Bunch(id=i) for i in range(3, 5)],
            count=4,
            next=None,
            previous="https://vms.example.com/api/v5/views/?page=1&page_size=1000",
        )
        mock_session.get.return_value = page1
        mock_session.request.return_value = page2

        view = View(session=mock_session)
        all_views = view.list()

        assert [v.id for v in all_views] == [1, 2, 3, 4]
        first_params = mock_session.get.call_args.kwargs.get("params", {})
        assert first_params.get("page_size") == DEFAULT_PAGE_SIZE


class TestSessionRequestApiVersionDedup:
    """Test that session.request() deduplicates API version prefixes.

    Regression tests for a bug where pagination URLs like:
        https://10.27.200.89/api/v1/snapshots/?page=2&page_size=10
    were stripped to "v1/snapshots/?page=2&..." by the iterator, then
    request() prepended "/api/v1/" again, producing /api/v1/v1/snapshots/ (404).
    """

    def _simulate_dedup(self, api_method, api_ver):
        """Simulate the deduplication logic from VmsSession.request()."""
        cleaned = api_method.strip("/")
        if cleaned.startswith(f"{api_ver}/"):
            cleaned = cleaned[len(api_ver) + 1:]
        return cleaned

    def test_no_double_version_v1(self):
        """Strips leading 'v1/' from api_method when api_ver='v1'."""
        assert self._simulate_dedup("v1/snapshots/?page=2&page_size=10", "v1") == "snapshots/?page=2&page_size=10"

    def test_no_double_version_v5(self):
        """Strips leading 'v5/' from api_method when api_ver='v5'."""
        assert self._simulate_dedup("v5/views/?page=3", "v5") == "views/?page=3"

    def test_no_strip_when_no_prefix(self):
        """Does not strip anything when api_method has no version prefix."""
        assert self._simulate_dedup("snapshots/", "v1") == "snapshots"

    def test_no_strip_when_version_mismatch(self):
        """Does not strip when api_method version differs from api_ver."""
        assert self._simulate_dedup("v5/views/?page=2", "v1") == "v5/views/?page=2"

    def test_no_strip_partial_match(self):
        """Does not strip when api_method only starts with version as substring."""
        # "v123resources/" does NOT start with "v1/" so should be untouched
        assert self._simulate_dedup("v123resources/", "v1") == "v123resources"

    def test_latest_version_dedup(self):
        """Handles 'latest' as api_ver for deduplication."""
        assert self._simulate_dedup("latest/snapshots/?page=2", "latest") == "snapshots/?page=2"
