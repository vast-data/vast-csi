"""
Comprehensive tests for concurrent token refresh behavior using condition variables.

These tests verify the thread-safe, single-authorization-at-a-time pattern
that prevents the "thundering herd" problem when multiple gRPC workers
attempt to refresh tokens simultaneously.
"""
import threading
import time
from unittest.mock import patch, MagicMock
from vast_csi.vms_session import get_vms_session, VmsSession
from vast_csi.configuration import Config
from vast_csi.exceptions import ApiError


class TestConcurrentTokenRefresh:
    """Tests for concurrent token refresh behavior using condition variables."""

    @patch("requests.Session.request")
    def test_concurrent_refresh_single_api_call(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that multiple concurrent workers trigger only ONE token refresh API call.
        
        This is the primary test for the "thundering herd" prevention.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        # Track API call count
        api_call_count = [0]
        call_lock = threading.Lock()
        
        def mock_token_response(*args, **kwargs):
            with call_lock:
                api_call_count[0] += 1
            # Simulate network latency
            time.sleep(0.1)
            mock_response = MagicMock()
            mock_response.json.return_value = {"access": f"token-{api_call_count[0]}"}
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_request.side_effect = mock_token_response
        
        # Simulate 10 concurrent workers all detecting 403 error
        num_workers = 10
        results = []
        threads = []
        
        def worker():
            session.refresh_auth_token()
            results.append(session.headers.get('authorization'))
        
        # Launch all workers simultaneously
        for _ in range(num_workers):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        # Wait for all workers to complete
        for t in threads:
            t.join()
        
        # Assert: Only 1 API call should have been made
        assert mock_request.call_count == 1, f"Expected 1 API call, got {mock_request.call_count}"
        
        # Assert: All workers should have the same token
        assert len(set(results)) == 1, "All workers should have the same token"
        assert results[0] == "Bearer token-1"

    @patch("requests.Session.request")
    def test_concurrent_refresh_with_failure_retry(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that if first worker fails, the next worker automatically retries.
        
        This tests the token clearing strategy.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        call_count = [0]
        call_lock = threading.Lock()
        
        def mock_token_response(*args, **kwargs):
            with call_lock:
                call_count[0] += 1
                current_call = call_count[0]
            
            time.sleep(0.05)  # Simulate latency
            
            if current_call == 1:
                # First call fails
                raise ConnectionError("Network timeout")
            else:
                # Second call succeeds
                mock_response = MagicMock()
                mock_response.json.return_value = {"access": "token-success"}
                mock_response.raise_for_status = MagicMock()
                return mock_response
        
        mock_request.side_effect = mock_token_response
        
        # Launch 5 concurrent workers
        num_workers = 5
        results = {"success": [], "failed": []}
        threads = []
        
        def worker():
            try:
                session.refresh_auth_token()
                results["success"].append(session.headers.get('authorization'))
            except (ApiError, ConnectionError):
                results["failed"].append(True)
        
        for _ in range(num_workers):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert: Exactly 2 API calls (1 failed, 1 succeeded)
        # First worker fails, sets _authorizing=False. Next waiting worker retries.
        assert mock_request.call_count == 2, f"Expected 2 API calls, got {mock_request.call_count}"
        
        # Assert: At least some workers succeeded with the retry
        assert len(results["success"]) > 0, "At least some workers should have succeeded"
        assert all(token == "Bearer token-success" for token in results["success"])

    @patch("requests.Session.request")
    def test_sequential_refresh_calls(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that sequential (non-concurrent) refresh calls each trigger a new API call.
        
        This ensures the condition variable doesn't prevent legitimate sequential refreshes.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        call_count = [0]
        
        def mock_token_response(*args, **kwargs):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.json.return_value = {"access": f"token-{call_count[0]}"}
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_request.side_effect = mock_token_response
        
        # Make 3 sequential refresh calls
        session.refresh_auth_token()
        assert session.headers.get('authorization') == "Bearer token-1"
        
        session.refresh_auth_token()
        assert session.headers.get('authorization') == "Bearer token-2"
        
        session.refresh_auth_token()
        assert session.headers.get('authorization') == "Bearer token-3"
        
        # Assert: 3 API calls for 3 sequential refreshes
        assert mock_request.call_count == 3

    @patch("requests.Session.request")
    def test_waiting_workers_use_successful_token(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that workers waiting on condition variable use the token from successful worker.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        # Slow token endpoint to ensure workers pile up
        def mock_token_response(*args, **kwargs):
            time.sleep(0.2)
            mock_response = MagicMock()
            mock_response.json.return_value = {"access": "shared-token"}
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_request.side_effect = mock_token_response
        
        results = []
        threads = []
        start_barrier = threading.Barrier(10)  # Ensure all threads start together
        
        def worker():
            start_barrier.wait()  # Wait for all threads to be ready
            session.refresh_auth_token()
            results.append(session.headers.get('authorization'))
        
        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert: All workers got the same token
        assert len(set(results)) == 1
        assert results[0] == "Bearer shared-token"
        
        # Assert: Only 1 API call despite 10 workers
        assert mock_request.call_count == 1

    @patch("requests.Session.request")
    def test_token_clearing_on_failure(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that token is cleared before refresh attempt, preventing stale token bugs.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        # Set initial token
        session.headers['authorization'] = "Bearer old-token"
        
        def mock_token_failure(*args, **kwargs):
            raise ConnectionError("Network error")
        
        mock_request.side_effect = mock_token_failure
        
        # Attempt refresh (will fail)
        try:
            session.refresh_auth_token()
        except (ApiError, ConnectionError):
            pass
        
        # Assert: Token should be cleared (empty string) after failed refresh
        # This prevents waiting workers from using stale/expired tokens
        assert session.headers.get('authorization') == ''

    @patch("requests.Session.request")
    def test_concurrent_refresh_with_multiple_failures(self, mock_request, monkeypatch, mock_credentials):
        """
        Test multiple workers retrying after repeated failures.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        call_count = [0]
        call_lock = threading.Lock()
        
        def mock_token_response(*args, **kwargs):
            with call_lock:
                call_count[0] += 1
                current_call = call_count[0]
            
            time.sleep(0.05)
            
            if current_call <= 2:
                # First 2 calls fail
                raise ConnectionError(f"Network timeout {current_call}")
            else:
                # Third call succeeds
                mock_response = MagicMock()
                mock_response.json.return_value = {"access": "final-token"}
                mock_response.raise_for_status = MagicMock()
                return mock_response
        
        mock_request.side_effect = mock_token_response
        
        results = {"success": [], "failed": []}
        threads = []
        
        def worker():
            try:
                session.refresh_auth_token()
                results["success"].append(session.headers.get('authorization'))
            except (ApiError, ConnectionError):
                results["failed"].append(True)
        
        # Launch workers in waves to trigger multiple retries
        for _ in range(3):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
            time.sleep(0.01)  # Slight delay between workers
        
        for t in threads:
            t.join()
        
        # Assert: Exactly 3 attempts (2 failed, 1 succeeded)
        # Waiting workers retry when they see empty token after previous worker fails
        assert mock_request.call_count == 3
        
        # Assert: At least one worker succeeded
        assert len(results["success"]) > 0
        assert results["success"][0] == "Bearer final-token"

    def test_condition_variable_initialization(self, monkeypatch, mock_credentials):
        """
        Test that condition variable is properly initialized with the lock.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        # Assert: Condition variable should be initialized
        assert hasattr(session, '_token_refresh_cond')
        assert isinstance(session._token_refresh_cond, threading.Condition)
        
        # Assert: Authorizing flag should be initialized
        assert hasattr(session, '_authorizing')
        assert session._authorizing == False

    @patch("requests.Session.request")
    def test_no_race_condition_on_authorization_flag(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that the _authorizing flag is properly protected and no race conditions occur.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        observed_authorizing_states = []
        state_lock = threading.Lock()
        
        def mock_token_response(*args, **kwargs):
            # Capture the state during refresh
            with state_lock:
                observed_authorizing_states.append(session._authorizing)
            time.sleep(0.1)
            mock_response = MagicMock()
            mock_response.json.return_value = {"access": "test-token"}
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_request.side_effect = mock_token_response
        
        threads = []
        for _ in range(5):
            t = threading.Thread(target=session.refresh_auth_token)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert: Only 1 API call
        assert mock_request.call_count == 1
        
        # Assert: _authorizing should be False after completion
        assert session._authorizing == False

    @patch("requests.Session.request")
    def test_finally_block_clears_authorizing_flag(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that the finally block always clears _authorizing flag, even on exceptions.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        def mock_token_exception(*args, **kwargs):
            raise ConnectionError("Network error")
        
        mock_request.side_effect = mock_token_exception
        
        # Attempt refresh (will fail)
        try:
            session.refresh_auth_token()
        except (ApiError, ConnectionError):
            pass
        
        # Assert: _authorizing flag should be cleared despite exception
        assert session._authorizing == False

    @patch("requests.Session.request")
    def test_concurrent_workers_different_sessions(self, mock_request, monkeypatch, mock_credentials):
        """
        Test that different session instances don't interfere with each other.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        
        # Create two separate sessions
        session1 = VmsSession.create(
            config=Config(), username="user1", password="pass1", token=None,
            tenant=None, endpoint="test.com", ssl_cert=None, cluster_name=None
        )
        session2 = VmsSession.create(
            config=Config(), username="user2", password="pass2", token=None,
            tenant=None, endpoint="test2.com", ssl_cert=None, cluster_name=None
        )
        
        call_count = [0]
        call_lock = threading.Lock()
        
        def mock_token_response(*args, **kwargs):
            with call_lock:
                call_count[0] += 1
                current_count = call_count[0]
            time.sleep(0.05)
            mock_response = MagicMock()
            mock_response.json.return_value = {"access": f"token-{current_count}"}
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_request.side_effect = mock_token_response
        
        threads = []
        
        # 5 workers for session1
        for _ in range(5):
            t = threading.Thread(target=session1.refresh_auth_token)
            threads.append(t)
            t.start()
        
        # 5 workers for session2
        for _ in range(5):
            t = threading.Thread(target=session2.refresh_auth_token)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Assert: 2 API calls (1 per session)
        assert mock_request.call_count == 2
        
        # Assert: Each session has its own token
        assert session1.headers.get('authorization') != session2.headers.get('authorization')

    @patch("requests.Session.request")
    def test_extreme_concurrency_500_threads(self, mock_request, monkeypatch, mock_credentials):
        """
        Stress test: 500 threads sharing one session, all triggering token refresh.
        Verify that only ONE token refresh HTTP call is made despite 500 concurrent workers.
        """
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
        session = get_vms_session()
        
        # Track how many times the actual token refresh HTTP call is made
        token_call_count = [0]
        token_call_lock = threading.Lock()
        
        def mock_token_and_api_request(*args, **kwargs):
            """Mock both token refresh and actual API calls"""
            url = args[1] if len(args) > 1 else kwargs.get('url', '')
            
            # Check if this is a token refresh call
            if '/v1/token/' in url:
                with token_call_lock:
                    token_call_count[0] += 1
                    call_number = token_call_count[0]
                
                # Simulate network latency to increase contention
                time.sleep(0.1)
                
                mock_response = MagicMock()
                mock_response.json.return_value = {"access": f"token-{call_number}"}
                mock_response.raise_for_status = MagicMock()
                mock_response.status_code = 200
                return mock_response
            
            # Otherwise it's an actual API call (like GET /views)
            mock_response = MagicMock()
            mock_response.status_code = 200
            # views.one() expects a list response
            mock_response.json.return_value = [
                {"id": 1, "name": "test-view", "path": "/test", "tenant_id": 1}
            ]
            return mock_response
        
        mock_request.side_effect = mock_token_and_api_request
        
        num_threads = 500
        threads = []
        results = {"success": 0, "failed": 0}
        results_lock = threading.Lock()
        
        def worker():
            """Each worker makes an API request which will trigger token refresh"""
            try:
                # Make a GET request - this will trigger token refresh on first call
                # since session starts with empty authorization header
                response = session.views.one(name="test-view")
                with results_lock:
                    results["success"] += 1
            except Exception as e:
                with results_lock:
                    results["failed"] += 1
                print(f"Worker failed: {e}")
        
        # Start all threads at roughly the same time
        for i in range(num_threads):
            t = threading.Thread(target=worker, name=f"worker-{i}")
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join(timeout=10)  # 10 second timeout per thread
        
        # Critical assertion: Only ONE token refresh should have occurred
        assert token_call_count[0] == 1, f"Expected exactly 1 token refresh call, got {token_call_count[0]}"
        
        # All workers should have succeeded
        assert results["success"] == num_threads, f"Expected {num_threads} successes, got {results['success']}"
        assert results["failed"] == 0, f"Expected 0 failures, got {results['failed']}"
        
        # Verify the session has a valid token
        assert session.headers.get('authorization') == "Bearer token-1"
