"""document classification suggestion columns

Adds nullable columns to documents for the ML document-type suggestion and its human review. Purely additive:
existing rows keep NULLs (reported as NOT_RUN) and no data is rewritten.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('ml_status', sa.String(length=20), nullable=True))
    op.add_column('documents', sa.Column('ml_label', sa.String(length=30), nullable=True))
    op.add_column('documents', sa.Column('ml_score', sa.Float(), nullable=True))
    op.add_column('documents', sa.Column('ml_low_confidence', sa.Boolean(), nullable=True))
    op.add_column('documents', sa.Column('ml_model_version', sa.String(length=80), nullable=True))
    op.add_column('documents', sa.Column('ml_classified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('documents', sa.Column('reviewed_label', sa.String(length=30), nullable=True))
    op.add_column('documents', sa.Column('reviewed_label_by', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('reviewed_label_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_documents_reviewed_label_by_users', 'documents', 'users', ['reviewed_label_by'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_documents_reviewed_label_by_users', 'documents', type_='foreignkey')
    for col in ('reviewed_label_at', 'reviewed_label_by', 'reviewed_label', 'ml_classified_at', 'ml_model_version', 'ml_low_confidence', 'ml_score', 'ml_label', 'ml_status'):
        op.drop_column('documents', col)
