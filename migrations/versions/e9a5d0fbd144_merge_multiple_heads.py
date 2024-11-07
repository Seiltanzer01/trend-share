"""Merge multiple heads

Revision ID: e9a5d0fbd144
Revises: ae59e8cbab47, ee6d192fd5e5
Create Date: 2024-11-08 01:40:09.849035

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9a5d0fbd144'
down_revision = ('ae59e8cbab47', 'ee6d192fd5e5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
