from fleet_platform.db.session import SyncSessionLocal, get_sync_db


def test_sync_session_imports():
    assert SyncSessionLocal is not None


def test_get_sync_db_is_context_manager():
    cm = get_sync_db()
    assert hasattr(cm, "__enter__")
    assert hasattr(cm, "__exit__")
