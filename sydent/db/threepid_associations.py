# -*- coding: utf-8 -*-

# Copyright 2014,2017 OpenMarket Ltd
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

from sydent.util import time_msec

from sydent.threepid import ThreepidAssociation
from sydent.threepid.signer import Signer

import logging


logger = logging.getLogger(__name__)


class LocalAssociationStore:
    def __init__(self, sydent):
        self.sydent = sydent

    def addOrUpdateAssociation(self, assoc):
        """
        Updates an association, or creates one if none exists with these parameters.

        :param assoc: The association to create or update.
        :type assoc: ThreepidAssociation
        """
        cur = self.sydent.db.cursor()

        # sqlite's support for upserts is atrocious
        cur.execute(
            "insert or replace into local_threepid_associations "
            "('medium', 'address', 'lookup_hash', 'mxid', 'ts', 'notBefore', 'notAfter')"
            " values (?, ?, ?, ?, ?, ?, ?)",
            (
                assoc.medium,
                assoc.address,
                assoc.lookup_hash,
                assoc.mxid,
                assoc.ts,
                assoc.not_before,
                assoc.not_after,
            ),
        )
        self.sydent.db.commit()

    def getAssociationsAfterId(self, afterId, limit=None):
        """
        Retrieves every association after the given ID.

        :param afterId: The ID after which to retrieve associations.
        :type afterId: int
        :param limit: The maximum number of associations to retrieve, or None if no
            limit.
        :type limit: int or None

        :return: The retrieved associations (in a dict[id, assoc]), and the highest ID
            retrieved (or None if no ID thus no association was retrieved).
        :rtype: tuple[dict[int, ThreepidAssociation] or int or None]
        """
        cur = self.sydent.db.cursor()

        if afterId is None:
            afterId = -1

        q = (
            "select id, medium, address, lookup_hash, mxid, ts, notBefore, notAfter from "
            "local_threepid_associations "
            "where id > ? order by id asc"
        )
        if limit is not None:
            q += " limit ?"
            res = cur.execute(q, (afterId, limit))
        else:
            # No no, no no no no, no no no no, no no, there's no limit.
            res = cur.execute(q, (afterId,))

        maxId = None

        assocs = {}
        for row in res.fetchall():
            assoc = ThreepidAssociation(
                row[1], row[2], row[3], row[4], row[5], row[6], row[7]
            )
            assocs[row[0]] = assoc
            maxId = row[0]

        return assocs, maxId

    def getSignedAssociationsAfterId(self, afterId, limit=None):
        """Get associations after a given ID, and sign them before returning

        :param afterId: The ID to return results after (not inclusive)
        :type afterId: int

        :param limit: The maximum amount of signed associations to return. None for no
            limit.
        :type limit: int|None

        :return: A tuple consisting of a dictionary containing the signed associations
            (id: assoc dict) and an int representing the maximum ID (which is None if
            there was no association to retrieve).
        :rtype: tuple[dict[int, dict[str, any]] or int or None]
        """
        assocs = {}

        (localAssocs, maxId) = self.getAssociationsAfterId(afterId, limit)

        signer = Signer(self.sydent)

        for localId in localAssocs:
            sgAssoc = signer.signedThreePidAssociation(localAssocs[localId])
            assocs[localId] = sgAssoc

        return assocs, maxId

    def removeAssociation(self, threepid, mxid):
        """
        Delete the association between a 3PID and a MXID, if it exists. If the
        association doesn't exist, log and do nothing.

        :param threepid: The 3PID of the binding to remove.
        :type threepid: dict[unicode, unicode]
        :param mxid: The MXID of the binding to remove.
        :type mxid: unicode
        """

        cur = self.sydent.db.cursor()

        # check to see if we have any matching associations first.
        # We use a REPLACE INTO because we need the resulting row to have
        # a new ID (such that we know it's a new change that needs to be
        # replicated) so there's no need to insert a deletion row if there's
        # nothing to delete.
        cur.execute(
            "SELECT COUNT(*) FROM local_threepid_associations "
            "WHERE medium = ? AND address = ? AND mxid = ?",
            (threepid["medium"], threepid["address"], mxid),
        )
        row = cur.fetchone()
        if row[0] > 0:
            ts = time_msec()
            cur.execute(
                "REPLACE INTO local_threepid_associations "
                "('medium', 'address', 'mxid', 'ts', 'notBefore', 'notAfter') "
                " values (?, ?, NULL, ?, null, null)",
                (threepid["medium"], threepid["address"], ts),
            )
            logger.info(
                "Deleting local assoc for %s/%s/%s replaced %d rows",
                threepid["medium"],
                threepid["address"],
                mxid,
                cur.rowcount,
            )
            self.sydent.db.commit()
        else:
            logger.info(
                "No local assoc found for %s/%s/%s",
                threepid["medium"],
                threepid["address"],
                mxid,
            )
            # we still consider this successful in the name of idempotency:
            # the binding to be deleted is not there, so we're in the desired state.


class GlobalAssociationStore:
    def __init__(self, sydent):
        self.sydent = sydent

    def signedAssociationStringForThreepid(self, medium, address):
        """
        Retrieve the JSON for the signed association matching the provided 3PID,
        if one exists.

        :param medium: The medium of the 3PID.
        :type medium: unicode
        :param address: The address of the 3PID.
        :type address: unicode

        :return: The signed association, or None if no association was found for this
            3PID.
        :rtype: unicode or None
        """
        cur = self.sydent.db.cursor()
        # We treat address as case-insensitive because that's true for all the
        # threepids we have currently (we treat the local part of email addresses as
        # case insensitive which is technically incorrect). If we someday get a
        # case-sensitive threepid, this can change.
        res = cur.execute(
            "select sgAssoc from global_threepid_associations where "
            "medium = ? and lower(address) = lower(?) and notBefore < ? and notAfter > ? "
            "order by ts desc limit 1",
            (medium, address, time_msec(), time_msec()),
        )

        row = res.fetchone()

        if not row:
            return None

        sgAssocStr = row[0]

        return sgAssocStr

    def getMxid(self, medium, address):
        """
        Retrieves the MXID associated with a 3PID.

        :param medium: The medium of the 3PID.
        :type medium: unicode
        :param address: The address of the 3PID.
        :type address: unicode

        :return: The associated MXID, or None if no MXID is associated with this 3PID.
        :rtype: unicode or None
        """
        cur = self.sydent.db.cursor()
        res = cur.execute(
            "select mxid from global_threepid_associations where "
            "medium = ? and lower(address) = lower(?) and notBefore < ? and notAfter > ? "
            "order by ts desc limit 1",
            (medium, address, time_msec(), time_msec()),
        )

        row = res.fetchone()

        if not row:
            return None

        return row[0]

    def getMxids(self, threepid_tuples):
        """Given a list of threepid_tuples, return the same list but with
        mxids appended to each tuple for which a match was found in the
        database for. Output is ordered by medium, address, timestamp DESC

        :param threepid_tuples: List containing (medium, address) tuples
        :type threepid_tuples: list[tuple[unicode]]

        :return: a list of (medium, address, mxid) tuples
        :rtype: list[tuple[unicode]]
        """
        cur = self.sydent.db.cursor()

        cur.execute(
            "CREATE TEMPORARY TABLE tmp_getmxids (medium VARCHAR(16), address VARCHAR(256))"
        )
        cur.execute(
            "CREATE INDEX tmp_getmxids_medium_lower_address ON tmp_getmxids (medium, lower(address))"
        )

        try:
            inserted_cap = 0
            while inserted_cap < len(threepid_tuples):
                cur.executemany(
                    "INSERT INTO tmp_getmxids (medium, address) VALUES (?, ?)",
                    threepid_tuples[inserted_cap : inserted_cap + 500],
                )
                inserted_cap += 500

            res = cur.execute(
                # 'notBefore' is the time the association starts being valid, 'notAfter' the the time at which
                # it ceases to be valid, so the ts must be greater than 'notBefore' and less than 'notAfter'.
                "SELECT gte.medium, gte.address, gte.ts, gte.mxid FROM global_threepid_associations gte "
                "JOIN tmp_getmxids ON gte.medium = tmp_getmxids.medium AND lower(gte.address) = lower(tmp_getmxids.address) "
                "WHERE gte.notBefore < ? AND gte.notAfter > ? "
                "ORDER BY gte.medium, gte.address, gte.ts DESC",
                (time_msec(), time_msec()),
            )

            results = []
            current = ()
            for row in res.fetchall():
                # only use the most recent entry for each
                # threepid (they're sorted by ts)
                if (row[0], row[1]) == current:
                    continue
                current = (row[0], row[1])
                results.append((row[0], row[1], row[3]))

        finally:
            cur.execute("DROP TABLE tmp_getmxids")

        return results

    def addAssociation(self, assoc, rawSgAssoc, originServer, originId, commit=True):
        """
        Saves an association received through either a replication push or a local push.

        :param assoc: The association to add as a high level object.
        :type assoc: sydent.threepid.ThreepidAssociation
        :param rawSgAssoc: The original raw bytes of the signed association.
        :type rawSgAssoc: dict[str, any]
        :param originServer: The name of the server the association was created on.
        :type originServer: str
        :param originId: The ID of the association on the server the association was
            created on.
        :type originId: int
        :param commit: Whether to commit the database transaction after inserting the
            association.
        :type commit: bool
        """
        cur = self.sydent.db.cursor()
        cur.execute(
            "insert or ignore into global_threepid_associations "
            "(medium, address, lookup_hash, mxid, ts, notBefore, notAfter, originServer, originId, sgAssoc) values "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assoc.medium,
                assoc.address,
                assoc.lookup_hash,
                assoc.mxid,
                assoc.ts,
                assoc.not_before,
                assoc.not_after,
                originServer,
                originId,
                rawSgAssoc,
            ),
        )
        if commit:
            self.sydent.db.commit()

    def lastIdFromServer(self, server):
        """
        Retrieves the ID of the last association received from the given peer.

        :param server:
        :type server: str

        :return: The the ID of the last association received from the peer, or None if
            no association has ever been received from that peer.
        :rtype: int or None
        """
        cur = self.sydent.db.cursor()
        res = cur.execute(
            "select max(originId),count(originId) from global_threepid_associations "
            "where originServer = ?",
            (server,),
        )
        row = res.fetchone()

        if row[1] == 0:
            return None

        return row[0]

    def removeAssociation(self, medium, address):
        """
        Removes any association stored for the provided 3PID.

        :param medium: The medium for the 3PID.
        :type medium: unicode
        :param address: The address for the 3PID.
        :type address: unicode
        """
        cur = self.sydent.db.cursor()
        cur.execute(
            "DELETE FROM global_threepid_associations WHERE "
            "medium = ? AND address = ?",
            (medium, address),
        )
        logger.info(
            "Deleted %d rows from global associations for %s/%s",
            cur.rowcount,
            medium,
            address,
        )
        self.sydent.db.commit()

    def retrieveMxidsForHashes(self, addresses):
        """Returns a mapping from hash: mxid from a list of given lookup_hash values

        :param addresses: An array of lookup_hash values to check against the db
        :type addresses: list[unicode]

        :returns a dictionary of lookup_hash values to mxids of all discovered matches
        :rtype: dict[unicode, unicode]
        """
        cur = self.sydent.db.cursor()

        cur.execute(
            "CREATE TEMPORARY TABLE tmp_retrieve_mxids_for_hashes "
            "(lookup_hash VARCHAR)"
        )
        cur.execute(
            "CREATE INDEX tmp_retrieve_mxids_for_hashes_lookup_hash ON "
            "tmp_retrieve_mxids_for_hashes(lookup_hash)"
        )

        results = {}
        try:
            # Convert list of addresses to list of tuples of addresses
            addresses = [(x,) for x in addresses]

            inserted_cap = 0
            while inserted_cap < len(addresses):
                cur.executemany(
                    "INSERT INTO tmp_retrieve_mxids_for_hashes(lookup_hash) "
                    "VALUES (?)",
                    addresses[inserted_cap : inserted_cap + 500],
                )
                inserted_cap += 500

            res = cur.execute(
                # 'notBefore' is the time the association starts being valid, 'notAfter' the the time at which
                # it ceases to be valid, so the ts must be greater than 'notBefore' and less than 'notAfter'.
                "SELECT gta.lookup_hash, gta.mxid FROM global_threepid_associations gta "
                "JOIN tmp_retrieve_mxids_for_hashes "
                "ON gta.lookup_hash = tmp_retrieve_mxids_for_hashes.lookup_hash "
                "WHERE gta.notBefore < ? AND gta.notAfter > ? "
                "ORDER BY gta.lookup_hash, gta.mxid, gta.ts",
                (time_msec(), time_msec()),
            )

            # Place the results from the query into a dictionary
            # Results are sorted from oldest to newest, so if there are multiple mxid's for
            # the same lookup hash, only the newest mapping will be returned
            for lookup_hash, mxid in res.fetchall():
                results[lookup_hash] = mxid

        finally:
            cur.execute("DROP TABLE tmp_retrieve_mxids_for_hashes")

        return results
