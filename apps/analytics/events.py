"""The event vocabulary.

Names come from this list, never from free strings. A registry keeps the table
queryable -- once names drift, every dashboard query needs a LIKE.
"""

TEST_STARTED = "test.started"
TEST_SUBMITTED = "test.submitted"
TEST_EXPIRED = "test.expired"

WRITING_STARTED = "writing.started"
WRITING_SUBMITTED = "writing.submitted"
WRITING_MODEL_REVEALED = "writing.model_revealed"

SPEAKING_SESSION_STARTED = "speaking.session_started"
SPEAKING_SESSION_COMPLETED = "speaking.session_completed"

VOCAB_RATED = "vocab.rated"
VOCAB_SECTION_VIEWED = "vocab.section_viewed"

PAGE_VIEWED = "page.viewed"
AUTH_SIGNUP = "auth.signup"
AUTH_LOGIN = "auth.login"

# Emitted by the server inside service functions: authoritative, unblockable,
# and written in the same transaction as the change it describes.
SERVER_EVENTS = {
    TEST_STARTED,
    TEST_SUBMITTED,
    TEST_EXPIRED,
    WRITING_SUBMITTED,
    SPEAKING_SESSION_COMPLETED,
    VOCAB_RATED,
    AUTH_SIGNUP,
    AUTH_LOGIN,
}

# Accepted from the browser. Anything not on this list is dropped, so a client
# cannot invent names and make the table unqueryable.
CLIENT_EVENTS = {
    PAGE_VIEWED,
    VOCAB_SECTION_VIEWED,
    WRITING_STARTED,
    WRITING_MODEL_REVEALED,
    SPEAKING_SESSION_STARTED,
}

ALL_EVENTS = SERVER_EVENTS | CLIENT_EVENTS
