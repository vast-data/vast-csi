"""
Resource iterator for automatic pagination handling.

This module provides the ResourceIterator class that abstracts away pagination
complexity for VAST API resources.
"""

import urllib.parse
from easypy.bunch import Bunch
from vast_csi.logging import logger


DEFAULT_PAGE_SIZE = 1000


class ResourceIterator:
    """
    Iterator for VAST API resources that handles pagination automatically.
    
    Iterator handles both paginated responses
    (with 'results', 'count', 'next', 'previous' fields) and non-paginated responses.
    """
    
    def __init__(self, resource, initial_params=None, page_size=DEFAULT_PAGE_SIZE, api_ver=None):
        """
        Initialize a ResourceIterator.
        
        Args:
            resource: VastResource instance (e.g., session.views)
            initial_params: Dict of query parameters for the first request
            page_size: Number of items per page.
                       Default DEFAULT_PAGE_SIZE forces the server to paginate so
                       VMS 5.5+ does not silently truncate large list responses
                       (e.g. /views/ capped at 16K).
                       Pass 0 to explicitly disable pagination (no page_size sent;
                       server returns its own default shape).
            api_ver: API version to use for requests
        """
        self.resource = resource
        self.session = resource.session
        self.initial_params = initial_params or {}
        self.page_size = page_size
        self.api_ver = api_ver
        
        # Add page_size to params if specified
        if self.page_size > 0 and 'page_size' not in self.initial_params:
            self.initial_params['page_size'] = self.page_size
        
        # Iterator state
        self._initialized = False
        self._current = []
        self._next_url = None
        self._previous_url = None
        self._total_count = -1
        self._current_page = 0
        self._err = None
    
    def _fetch_page(self, url=None, params=None):
        """
        Fetch a page of results.
        
        Args:
            url: Full URL for next/previous navigation (optional)
            params: Query parameters for first request (optional)
        
        Returns:
            Bunch object with response data
        """
        if url:
            # Use the full URL for next/previous navigation
            # Extract path from URL for the request
            parsed = urllib.parse.urlparse(url)
            # The path already contains the full API path including version (e.g., /api/v5/views/?page=2)
            # Strip leading /api/ and use the rest as-is to preserve the correct version
            path_with_params = parsed.path + ('?' + parsed.query if parsed.query else '')
            # Remove leading /api/ prefix if present to get the version-qualified path
            if path_with_params.startswith('/api/'):
                path_with_params = path_with_params[5:]  # Remove '/api/' prefix
            response = self.session.request("GET", path_with_params, params=None)
        else:
            # Use resource path with params for first request
            response = self.session.get(self.resource.resource_name, api_ver=self.api_ver, params=params or self.initial_params)
        
        return self._process_response(response)
    
    def _process_response(self, response):
        """
        Process API response and extract pagination metadata.
        
        Args:
            response: Bunch object from API
        
        Returns:
            List of records from current page
        """
        # Check if this is a paginated response
        if isinstance(response, Bunch) and 'results' in response and 'count' in response:
            # Paginated response
            self._current = response.results or []
            self._total_count = response.count or 0
            self._next_url = response.get('next')
            self._previous_url = response.get('previous')
        elif isinstance(response, (list, tuple)):
            # Non-paginated list response
            self._current = list(response)
            self._total_count = len(self._current)
            self._next_url = None
            self._previous_url = None
        elif isinstance(response, Bunch):
            # Single object response (treat as single-item list)
            self._current = [response]
            self._total_count = 1
            self._next_url = None
            self._previous_url = None
        else:
            # Unexpected response type
            logger.warning(f"Unexpected response type in ResourceIterator: {type(response)}")
            self._current = []
            self._total_count = 0
            self._next_url = None
            self._previous_url = None
        
        return self._current
    
    def next(self):
        """
        Advance to the next page and return its records.
        
        Returns:
            List of records from the next page, or empty list if no more pages
        """
        if not self._initialized:
            self._fetch_page(params=self.initial_params)
            self._initialized = True
            return self._current
        
        if not self.has_next():
            return []
        
        self._current_page += 1
        return self._fetch_page(url=self._next_url)
    
    def previous(self):
        """
        Move to the previous page and return its records.
        
        Returns:
            List of records from the previous page, or empty list if no previous page
        """
        if not self._initialized:
            raise RuntimeError("Iterator not initialized, call next() first")
        
        if not self.has_previous():
            return []
        
        self._current_page -= 1
        return self._fetch_page(url=self._previous_url)
    
    def has_next(self):
        """
        Check if there is a next page available.
        
        Returns:
            True if there is a next page, False otherwise
        """
        if not self._initialized:
            return True
        return self._next_url is not None and self._next_url != ""
    
    def has_previous(self):
        """
        Check if there is a previous page available.
        
        Returns:
            True if there is a previous page, False otherwise
        """
        if not self._initialized:
            return False
        return self._previous_url is not None and self._previous_url != ""
    
    def count(self):
        """
        Get the total count of items.
        
        Returns:
            Total count if available, -1 otherwise
        """
        return self._total_count
    
    def page_size(self):
        """
        Get the configured page size.
        
        Returns:
            Page size (may be 0 if using API default)
        """
        return self.page_size
    
    def reset(self):
        """
        Reset the iterator to the first page and return its records.
        
        Returns:
            List of records from the first page
        """
        self._initialized = False
        self._current = []
        self._next_url = None
        self._previous_url = None
        self._current_page = 0
        self._err = None
        self._total_count = -1
        
        return self.next()
    
    def all(self):
        """
        Fetch all pages and return all records as a single list.
        Use with caution for large datasets.
        
        Returns:
            List of all records across all pages
        """
        all_records = []
        
        if not self._initialized:
            records = self.next()
            all_records.extend(records)
        else:
            # Include current page if already initialized
            all_records.extend(self._current)
        
        while self.has_next():
            records = self.next()
            all_records.extend(records)
        
        return all_records
    
    def __iter__(self):
        """Make the iterator iterable for use in for loops"""
        return self
    
    def __next__(self):
        """Support Python iterator protocol"""
        if not self._initialized:
            # First call - initialize and return first page
            return self.next()
        
        if not self.has_next():
            raise StopIteration
        
        return self.next()
    
    def __str__(self):
        return (
            f"ResourceIterator(\n"
            f"  resource={self.resource.resource_name},\n"
            f"  initialized={self._initialized},\n"
            f"  current_page={self._current_page},\n"
            f"  page_size={self.page_size},\n"
            f"  total_count={self._total_count},\n"
            f"  current_records={len(self._current)},\n"
            f"  has_next={self.has_next()},\n"
            f"  has_previous={self.has_previous()}\n"
            f")"
        )
