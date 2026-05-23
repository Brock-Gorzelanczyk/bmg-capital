from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.social import Post, PostLike, Comment, UserFollow

router = APIRouter(prefix="/api/social", tags=["social"])


def _ser_post(p: Post, current_user_id: int, db: Session) -> dict:
    author = db.query(User).filter_by(id=p.user_id).first()
    liked = db.query(PostLike).filter_by(post_id=p.id, user_id=current_user_id).first() is not None
    return {
        "id": p.id,
        "user_id": p.user_id,
        "username": author.username if author else "unknown",
        "symbol": p.symbol,
        "content": p.content,
        "likes_count": p.likes_count,
        "comments_count": p.comments_count,
        "is_memo": p.is_memo,
        "liked_by_me": liked,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── Feed ────────────────────────────────────────────────────────────────────

@router.get("/feed")
def feed(
    symbol: Optional[str] = None,
    memos_only: bool = False,
    limit: int = Query(30, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Post)
    if symbol:
        q = q.filter(Post.symbol == symbol.upper())
    if memos_only:
        q = q.filter(Post.is_memo.is_(True))
    posts = q.order_by(desc(Post.created_at)).limit(limit).all()
    return [_ser_post(p, current_user.id, db) for p in posts]


# ── Posts ───────────────────────────────────────────────────────────────────

class PostBody(BaseModel):
    content: str
    symbol: Optional[str] = None
    is_memo: bool = False


@router.post("/posts")
def create_post(
    body: PostBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    post = Post(
        user_id=current_user.id,
        symbol=body.symbol.upper() if body.symbol else None,
        content=body.content.strip(),
        is_memo=body.is_memo,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _ser_post(post, current_user.id, db)


@router.delete("/posts/{post_id}")
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter_by(id=post_id, user_id=current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()
    return {"ok": True}


# ── Likes ───────────────────────────────────────────────────────────────────

@router.post("/posts/{post_id}/like")
def toggle_like(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    existing = db.query(PostLike).filter_by(post_id=post_id, user_id=current_user.id).first()
    if existing:
        db.delete(existing)
        post.likes_count = max(0, post.likes_count - 1)
        liked = False
    else:
        db.add(PostLike(post_id=post_id, user_id=current_user.id))
        post.likes_count += 1
        liked = True
    db.commit()
    return {"liked": liked, "likes_count": post.likes_count}


# ── Comments ─────────────────────────────────────────────────────────────────

@router.get("/posts/{post_id}/comments")
def get_comments(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Comment).filter_by(post_id=post_id).order_by(Comment.created_at).all()
    result = []
    for c in rows:
        author = db.query(User).filter_by(id=c.user_id).first()
        result.append({
            "id": c.id,
            "post_id": c.post_id,
            "user_id": c.user_id,
            "username": author.username if author else "unknown",
            "content": c.content,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return result


class CommentBody(BaseModel):
    content: str


@router.post("/posts/{post_id}/comments")
def add_comment(
    post_id: int,
    body: CommentBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    comment = Comment(post_id=post_id, user_id=current_user.id, content=body.content.strip())
    db.add(comment)
    post.comments_count += 1
    db.commit()
    db.refresh(comment)
    author = db.query(User).filter_by(id=current_user.id).first()
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "user_id": comment.user_id,
        "username": author.username if author else "unknown",
        "content": comment.content,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


# ── Follow ───────────────────────────────────────────────────────────────────

@router.post("/follow/{user_id}")
def toggle_follow(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    target = db.query(User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(UserFollow).filter_by(follower_id=current_user.id, following_id=user_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False}
    db.add(UserFollow(follower_id=current_user.id, following_id=user_id))
    db.commit()
    return {"following": True}


@router.get("/following")
def get_following(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(UserFollow).filter_by(follower_id=current_user.id).all()
    ids = [r.following_id for r in rows]
    users = db.query(User).filter(User.id.in_(ids)).all() if ids else []
    return [{"id": u.id, "username": u.username} for u in users]
