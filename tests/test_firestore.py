"""Tests for Firestore client (mocked — no real Firestore needed)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend import firestore_client


@pytest.fixture(autouse=True)
def reset_firestore():
    """Reset Firestore client state between tests."""
    firestore_client._db = None
    firestore_client._init_attempted = False
    yield


class TestSaveSession:
    @pytest.mark.asyncio
    async def test_save_session_no_firestore(self):
        """When Firestore is not available, save returns None gracefully."""
        firestore_client._init_attempted = True
        firestore_client._db = None
        result = await firestore_client.save_session({"session_id": "test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_save_session_with_firestore(self):
        """When Firestore is available, save writes and returns session_id."""
        mock_doc_ref = AsyncMock()
        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref

        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection

        firestore_client._init_attempted = True
        firestore_client._db = mock_db

        data = {"session_id": "abc123", "exercise": "squat", "total_reps": 10}
        result = await firestore_client.save_session(data)

        assert result == "abc123"
        mock_db.collection.assert_called_with("sessions")
        mock_collection.document.assert_called_with("abc123")
        mock_doc_ref.set.assert_called_once_with(data)


class TestGetSession:
    @pytest.mark.asyncio
    async def test_get_session_no_firestore(self):
        firestore_client._init_attempted = True
        firestore_client._db = None
        result = await firestore_client.get_session("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_found(self):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"session_id": "abc", "exercise": "squat"}

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get.return_value = mock_doc

        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref

        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection

        firestore_client._init_attempted = True
        firestore_client._db = mock_db

        result = await firestore_client.get_session("abc")
        assert result == {"session_id": "abc", "exercise": "squat"}

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        mock_doc = MagicMock()
        mock_doc.exists = False

        mock_doc_ref = AsyncMock()
        mock_doc_ref.get.return_value = mock_doc

        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref

        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection

        firestore_client._init_attempted = True
        firestore_client._db = mock_db

        result = await firestore_client.get_session("nope")
        assert result is None


class TestGetUserSessions:
    @pytest.mark.asyncio
    async def test_no_firestore(self):
        firestore_client._init_attempted = True
        firestore_client._db = None
        result = await firestore_client.get_user_sessions("user-1")
        assert result == []
