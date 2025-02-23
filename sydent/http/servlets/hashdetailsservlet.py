# -*- coding: utf-8 -*-

# Copyright 2019 The Matrix.org Foundation C.I.C.
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
from __future__ import absolute_import

from twisted.web.resource import Resource
from sydent.http.auth import authV2

import logging

from sydent.http.servlets import jsonwrap, send_cors


logger = logging.getLogger(__name__)


class HashDetailsServlet(Resource):
    isLeaf = True
    known_algorithms = ["sha256", "none"]

    def __init__(self, syd, lookup_pepper):
        self.sydent = syd
        self.lookup_pepper = lookup_pepper

    @jsonwrap
    def render_GET(self, request):
        """
        Return the hashing algorithms and pepper that this IS supports. The
        pepper included in the response is stored in the database, or
        otherwise generated.

        Returns: An object containing an array of hashing algorithms the
                 server supports, and a `lookup_pepper` field, which is a
                 server-defined value that the client should include in the 3PID
                 information before hashing.
        """
        send_cors(request)

        authV2(self.sydent, request)

        return {
            "algorithms": self.known_algorithms,
            "lookup_pepper": self.lookup_pepper,
        }

    def render_OPTIONS(self, request):
        send_cors(request)
        return b""
