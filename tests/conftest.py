from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def seed_data(db_session):
    """Küçük test evreni: 1 site, 2 blok, 2'şer daire, her rolden kullanıcı."""
    pw = hash_password("test1234")
    site = models.Site(name="Test Sitesi")
    db_session.add(site)
    db_session.flush()

    block_a = models.Block(site_id=site.id, name="A")
    block_b = models.Block(site_id=site.id, name="B")
    db_session.add_all([block_a, block_b])
    db_session.flush()

    apartments = [
        models.Apartment(block_id=block_a.id, floor_no=1, number="1"),
        models.Apartment(block_id=block_a.id, floor_no=1, number="2"),
        models.Apartment(block_id=block_b.id, floor_no=1, number="1"),
        models.Apartment(block_id=block_b.id, floor_no=1, number="2"),
    ]
    db_session.add_all(apartments)
    db_session.flush()

    admin = models.User(email="admin@test", full_name="Admin", role=models.ROLE_SITE_MANAGER, password_hash=pw)
    manager = models.User(email="manager@test", full_name="Yönetici A", role=models.ROLE_BUILDING_MANAGER,
                          block_id=block_a.id, password_hash=pw)
    resident = models.User(email="resident@test", full_name="Sakin", role=models.ROLE_RESIDENT, password_hash=pw)
    other = models.User(email="other@test", full_name="Diğer Sakin", role=models.ROLE_RESIDENT, password_hash=pw)
    db_session.add_all([admin, manager, resident, other])
    db_session.flush()

    db_session.add_all([
        models.Occupancy(apartment_id=apartments[0].id, user_id=resident.id, type=models.OCC_TENANT,
                         start_date=date(2026, 1, 1)),
        models.Occupancy(apartment_id=apartments[2].id, user_id=other.id, type=models.OCC_OWNER,
                         start_date=date(2026, 1, 1)),
    ])

    dues = models.DuesDefinition(
        site_id=site.id, period="2026-07", amount=Decimal("500.00"), due_date=date(2026, 7, 10)
    )
    db_session.add(dues)
    db_session.commit()

    return {
        "site": site, "block_a": block_a, "block_b": block_b, "apartments": apartments,
        "admin": admin, "manager": manager, "resident": resident, "other": other, "dues": dues,
    }


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
