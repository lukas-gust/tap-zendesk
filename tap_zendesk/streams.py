import os
import json
import singer

from singer import metadata
from singer import utils

LOGGER = singer.get_logger()
KEY_PROPERTIES = ['id']

def get_abs_path(path):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

class Stream():
    name = None
    replication_method = None
    replication_key = None
    key_properties = KEY_PROPERTIES

    def __init__(self, client=None):
        self.client = client

    def get_bookmark(self, state):
        return utils.strptime_with_tz(singer.get_bookmark(state, self.name, self.replication_key))

    def update_bookmark(self, state, value):
        singer.write_bookmark(state, self.name, self.replication_key, value)

    def load_schema(self):
        schema_file = "schemas/{}.json".format(self.name)
        with open(get_abs_path(schema_file)) as f:
            schema = json.load(f)
        return schema

    def load_metadata(self):
        schema = self.load_schema()
        mdata = metadata.new()

        mdata = metadata.write(mdata, (), 'table-key-properties', self.key_properties)
        mdata = metadata.write(mdata, (), 'forced-replication-method', self.replication_method)

        for field_name in schema['properties'].keys():
            if field_name in KEY_PROPERTIES:
                mdata = metadata.write(mdata, ('properties', field_name), 'inclusion', 'automatic')
            else:
                mdata = metadata.write(mdata, ('properties', field_name), 'inclusion', 'available')

        return metadata.to_list(mdata)

class Organizations(Stream):
    name = "organizations"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)
        organizations = self.client.organizations.incremental(start_time=bookmark)
        for organization in organizations:
            self.update_bookmark(state, organization.updated_at)
            yield organization

class Users(Stream):
    name = "users"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)
        users = self.client.users.incremental(start_time=bookmark)
        for user in users:
            self.update_bookmark(state, user.updated_at)
            yield user

class Tickets(Stream):
    name = "tickets"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)
        tickets = self.client.tickets.incremental(start_time=bookmark)
        for ticket in tickets:
            self.update_bookmark(state, ticket.updated_at)
            yield ticket

class TicketAudits(Stream):
    name = "ticket-audits"
    replication_method = "INCREMENTAL"
    replication_key = "created_at"

    def update_cursor_bookmark(self, state, audit_generator):
        # NB: Zenpy auto-advances cursor's pages, so each iteration, we need to
        #  check if our most-recent-previous-cursor-bookmark has changed
        cursor_advanced = audit_generator.before_cursor != singer.get_bookmark(state, self.name, 'cursor_value')
        if cursor_advanced:
            singer.write_bookmark(state, self.name, 'cursor_value', audit_generator.before_cursor)

    def advance_cursor(self, audit_generator, bookmark, state):
        for audit in reversed(audit_generator):
            self.update_cursor_bookmark(state, audit_generator)
            if utils.strptime_with_tz(audit.created_at) < bookmark:
                continue
            else:
                audit_generator.position -= 1
                break

        return audit_generator

    def sync(self, state):
        bookmark = self.get_bookmark(state)

        cursor_bookmark = singer.get_bookmark(state, self.name, 'cursor_value')
        if cursor_bookmark:
            audit_generator = self.client.tickets.audits(cursor=cursor_bookmark)
        else:
            audit_generator = self.client.tickets.audits()


        # TODO: Records seem to be emitting in reverse order
        self.advance_cursor(audit_generator, bookmark, state)
        for audit in audit_generator:
            self.update_cursor_bookmark(state, audit_generator)
            self.update_bookmark(state, audit.created_at)
            yield audit

class Groups(Stream):
    name = "groups"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)

        groups = self.client.groups()
        for group in groups:
            if utils.strptime_with_tz(group.updated_at) >= bookmark:
                self.update_bookmark(state, group.updated_at)
                yield group

class Macros(Stream):
    name = "macros"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)

        macros = self.client.macros()
        for macro in macros:
            if utils.strptime_with_tz(macro.updated_at) >= bookmark:
                self.update_bookmark(state, macro.updated_at)
                yield macro

class Tags(Stream):
    name = "tags"
    replication_method = "FULL_TABLE"
    key_properties = []

    def sync(self, state): # pylint: disable=unused-argument
        return self.client.tags()

class TicketFields(Stream):
    name = "ticket-fields"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)

        fields = self.client.ticket_fields()
        for field in fields:
            if utils.strptime_with_tz(field.updated_at) >= bookmark:
                self.update_bookmark(state, field.updated_at)
                yield field

class TicketMetrics(Stream):
    name = "ticket-metrics"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"
    # TODO: State isn't updating, is null at end of sync

    def sync(self, state):
        bookmark = self.get_bookmark(state)
        ticket_metrics = self.client.tickets.metrics_incremental(start_time=bookmark)

        for ticket_metric in ticket_metrics:
            self.update_bookmark(state, ticket_metric.updated_at)
            yield ticket_metric

class GroupMemberships(Stream):
    name = "group-memberships"
    replication_method = "INCREMENTAL"
    replication_key = "updated_at"

    def sync(self, state):
        bookmark = self.get_bookmark(state)

        memberships = self.client.group_memberships()
        for membership in memberships:
            if utils.strptime_with_tz(membership.updated_at) >= bookmark:
                self.update_bookmark(state, membership.updated_at)
                yield membership


STREAMS = {
    "tickets": Tickets,
    "groups": Groups,
    "users": Users,
    "organizations": Organizations,
    "ticket-audits": TicketAudits,
    "ticket-fields": TicketFields,
    "group-memberships": GroupMemberships,
    "macros": Macros,
    "tags": Tags,
    "ticket-metrics": TicketMetrics
}


    # stream = {
    #     "tap_stream_id": stream_name,
    #     "stream": stream_name,
    #     "key_properties": ["Id"],
    #     "schema": {
    #         "type": "object",
    #         "additionalProperties": False,
    #         "properties": properties,
    #     },
    #     'metadata': metadata.to_list(mdata)
    # }
