#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL."""
import sys
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from models.database import Base
from models.user import User
from models.paper import Paper, PaperVersion, PaperHumanAuthor, PaperAIAuthor, PaperField
from models.comment import Comment, CommentVote

def migrate_data():
    """Migrate all data from SQLite to PostgreSQL."""
    print("=" * 60)
    print("JAIGP Database Migration: SQLite → PostgreSQL")
    print("=" * 60)

    # Source (SQLite)
    sqlite_url = "sqlite:///./data/jaip.db"
    print(f"\n📂 Source: {sqlite_url}")

    # Destination (PostgreSQL)
    postgres_url = "postgresql://jaigp_user:jaigp_secure_pass_2026@localhost/jaigp"
    print(f"📂 Destination: postgresql://jaigp_user:***@localhost/jaigp")

    # Create engines
    print("\n🔌 Connecting to databases...")
    sqlite_engine = create_engine(sqlite_url)
    postgres_engine = create_engine(postgres_url)

    # Create all tables in PostgreSQL
    print("🏗️  Creating tables in PostgreSQL...")
    Base.metadata.create_all(postgres_engine)
    print("✅ Tables created")

    # Create sessions
    sqlite_session = Session(sqlite_engine)
    postgres_session = Session(postgres_engine)

    try:
        # Migrate Users
        print("\n👥 Migrating users...")
        users = sqlite_session.query(User).all()
        for user in users:
            # Create new user with same data
            new_user = User(
                id=user.id,
                orcid_id=user.orcid_id,
                name=user.name,
                email=user.email,
                google_scholar_url=user.google_scholar_url,
                rankless_url=user.rankless_url,
                affiliation=user.affiliation,
                created_at=user.created_at,
                updated_at=user.updated_at
            )
            postgres_session.merge(new_user)
        postgres_session.commit()
        print(f"✅ Migrated {len(users)} users")

        # Migrate Papers
        print("\n📄 Migrating papers...")
        papers = sqlite_session.query(Paper).all()
        for paper in papers:
            new_paper = Paper(
                id=paper.id,
                title=paper.title,
                abstract=paper.abstract,
                current_version=paper.current_version,
                submission_date=paper.submission_date,
                published_date=paper.published_date,
                status=paper.status,
                image_filename=paper.image_filename,
                created_at=paper.created_at,
                updated_at=paper.updated_at
            )
            postgres_session.merge(new_paper)
        postgres_session.commit()
        print(f"✅ Migrated {len(papers)} papers")

        # Migrate Paper Versions
        print("\n📝 Migrating paper versions...")
        versions = sqlite_session.query(PaperVersion).all()
        for version in versions:
            new_version = PaperVersion(
                id=version.id,
                paper_id=version.paper_id,
                version_number=version.version_number,
                pdf_filename=version.pdf_filename,
                change_log=version.change_log,
                created_at=version.created_at
            )
            postgres_session.merge(new_version)
        postgres_session.commit()
        print(f"✅ Migrated {len(versions)} versions")

        # Migrate Human Authors
        print("\n✍️  Migrating human authors...")
        human_authors = sqlite_session.query(PaperHumanAuthor).all()
        for author in human_authors:
            new_author = PaperHumanAuthor(
                id=author.id,
                paper_id=author.paper_id,
                user_id=author.user_id,
                author_order=author.author_order,
                contribution=author.contribution
            )
            postgres_session.merge(new_author)
        postgres_session.commit()
        print(f"✅ Migrated {len(human_authors)} human author records")

        # Migrate AI Authors
        print("\n🤖 Migrating AI authors...")
        ai_authors = sqlite_session.query(PaperAIAuthor).all()
        for ai in ai_authors:
            new_ai = PaperAIAuthor(
                id=ai.id,
                paper_id=ai.paper_id,
                ai_name=ai.ai_name,
                ai_version=ai.ai_version,
                ai_role=ai.ai_role,
                author_order=ai.author_order,
                additional_info=ai.additional_info
            )
            postgres_session.merge(new_ai)
        postgres_session.commit()
        print(f"✅ Migrated {len(ai_authors)} AI author records")

        # Migrate Paper Fields
        print("\n🏷️  Migrating paper fields...")
        fields = sqlite_session.query(PaperField).all()
        for field in fields:
            new_field = PaperField(
                id=field.id,
                paper_id=field.paper_id,
                field_type=field.field_type,
                field_id=field.field_id,
                field_name=field.field_name,
                display_name=field.display_name
            )
            postgres_session.merge(new_field)
        postgres_session.commit()
        print(f"✅ Migrated {len(fields)} field records")

        # Migrate Comments
        print("\n💬 Migrating comments...")
        comments = sqlite_session.query(Comment).all()
        for comment in comments:
            new_comment = Comment(
                id=comment.id,
                paper_id=comment.paper_id,
                user_id=comment.user_id,
                content=comment.content,
                created_at=comment.created_at,
                updated_at=comment.updated_at
            )
            postgres_session.merge(new_comment)
        postgres_session.commit()
        print(f"✅ Migrated {len(comments)} comments")

        # Migrate Comment Votes
        print("\n👍 Migrating comment votes...")
        votes = sqlite_session.query(CommentVote).all()
        for vote in votes:
            new_vote = CommentVote(
                id=vote.id,
                comment_id=vote.comment_id,
                user_id=vote.user_id,
                vote_type=vote.vote_type,
                created_at=vote.created_at
            )
            postgres_session.merge(new_vote)
        postgres_session.commit()
        print(f"✅ Migrated {len(votes)} votes")

        # Update sequences
        print("\n🔢 Updating PostgreSQL sequences...")
        tables = ['users', 'papers', 'paper_versions', 'paper_human_authors',
                  'paper_ai_authors', 'paper_fields', 'comments', 'comment_votes']

        for table in tables:
            try:
                result = postgres_session.execute(
                    text(f"SELECT setval('{table}_id_seq', (SELECT MAX(id) FROM {table}));")
                )
                postgres_session.commit()
                print(f"✅ Updated {table} sequence")
            except Exception as e:
                print(f"⚠️  Could not update {table} sequence: {e}")
                postgres_session.rollback()

        print("\n" + "=" * 60)
        print("🎉 Migration completed successfully!")
        print("=" * 60)
        print("\n📊 Summary:")
        print(f"  • Users: {len(users)}")
        print(f"  • Papers: {len(papers)}")
        print(f"  • Versions: {len(versions)}")
        print(f"  • Human Authors: {len(human_authors)}")
        print(f"  • AI Authors: {len(ai_authors)}")
        print(f"  • Fields: {len(fields)}")
        print(f"  • Comments: {len(comments)}")
        print(f"  • Votes: {len(votes)}")
        print("\n✅ You can now update config.py to use PostgreSQL")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        postgres_session.rollback()
        raise
    finally:
        sqlite_session.close()
        postgres_session.close()

if __name__ == "__main__":
    print("\n⚠️  WARNING: This will copy all data from SQLite to PostgreSQL")
    print("Make sure PostgreSQL is running and the database 'jaigp' exists.")

    response = input("\nProceed with migration? (yes/no): ")
    if response.lower() == 'yes':
        migrate_data()
    else:
        print("Migration cancelled.")
