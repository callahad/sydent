# -*- coding: utf-8 -*-
# Copyright 2019 New Vector Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import time

import attr
from sortedcontainers import SortedList

logger = logging.getLogger(__name__)

SENTINEL = object()


class TTLCache(object):
    """A key/value cache implementation where each entry has its own TTL"""

    def __init__(self, cache_name, timer=time.time):
        # map from key to _CacheEntry
        self._data = {}

        # the _CacheEntries, sorted by expiry time
        self._expiry_list = SortedList()

        self._timer = timer

    def set(self, key, value, ttl):
        """Add/update an entry in the cache

        :param key: Key for this entry.

        :param value: Value for this entry.

        :param paramttl: TTL for this entry, in seconds.
        :type paramttl: float
        """
        expiry = self._timer() + ttl

        self.expire()
        e = self._data.pop(key, SENTINEL)
        if e != SENTINEL:
            self._expiry_list.remove(e)

        entry = _CacheEntry(expiry_time=expiry, key=key, value=value)
        self._data[key] = entry
        self._expiry_list.add(entry)

    def get(self, key, default=SENTINEL):
        """Get a value from the cache

        :param key: The key to look up.
        :param default: default value to return, if key is not found. If not
            set, and the key is not found, a KeyError will be raised.

        :returns a value from the cache, or the default.
        """
        self.expire()
        e = self._data.get(key, SENTINEL)
        if e == SENTINEL:
            if default == SENTINEL:
                raise KeyError(key)
            return default
        return e.value

    def get_with_expiry(self, key):
        """Get a value, and its expiry time, from the cache

        :param key: key to look up

        :returns The value from the cache, and the expiry time.
        :rtype: Tuple[Any, float]

        Raises:
            KeyError if the entry is not found
        """
        self.expire()
        try:
            e = self._data[key]
        except KeyError:
            raise
        return e.value, e.expiry_time

    def pop(self, key, default=SENTINEL):
        """Remove a value from the cache

        If key is in the cache, remove it and return its value, else return default.
        If default is not given and key is not in the cache, a KeyError is raised.

        :param key: key to look up
        :param default: default value to return, if key is not found. If not
            set, and the key is not found, a KeyError will be raised

        :returns a value from the cache, or the default
        """
        self.expire()
        e = self._data.pop(key, SENTINEL)
        if e == SENTINEL:
            if default == SENTINEL:
                raise KeyError(key)
            return default
        self._expiry_list.remove(e)
        return e.value

    def __getitem__(self, key):
        return self.get(key)

    def __delitem__(self, key):
        self.pop(key)

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        self.expire()
        return len(self._data)

    def expire(self):
        """Run the expiry on the cache. Any entries whose expiry times are due will
        be removed
        """
        now = self._timer()
        while self._expiry_list:
            first_entry = self._expiry_list[0]
            if first_entry.expiry_time - now > 0.0:
                break
            del self._data[first_entry.key]
            del self._expiry_list[0]


@attr.s(frozen=True, slots=True)
class _CacheEntry(object):
    """TTLCache entry"""

    # expiry_time is the first attribute, so that entries are sorted by expiry.
    expiry_time = attr.ib()
    key = attr.ib()
    value = attr.ib()
