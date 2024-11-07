"""Описание изменений

Revision ID: 952aaafcbf7f
Revises: e9a5d0fbd144
Create Date: 2024-11-08 02:46:22.635653

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '952aaafcbf7f'
down_revision = 'e9a5d0fbd144'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_id', sa.BigInteger(), nullable=False))
        batch_op.add_column(sa.Column('username', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('first_name', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('last_name', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('auth_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('auth_token_creation_time', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('registered_at', sa.DateTime(), nullable=False))
        batch_op.create_unique_constraint('uq_user_auth_token', ['auth_token'])
        batch_op.create_unique_constraint('uq_user_telegram_id', ['telegram_id'])
        batch_op.create_unique_constraint('uq_user_username', ['username'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('uq_user_username', type_='unique')
        batch_op.drop_constraint('uq_user_telegram_id', type_='unique')
        batch_op.drop_constraint('uq_user_auth_token', type_='unique')
        batch_op.drop_column('registered_at')
        batch_op.drop_column('auth_token_creation_time')
        batch_op.drop_column('auth_token')
        batch_op.drop_column('last_name')
        batch_op.drop_column('first_name')
        batch_op.drop_column('username')
        batch_op.drop_column('telegram_id')

    # ### end Alembic commands ###
