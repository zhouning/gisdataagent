"""
消息总线监控 REST API
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from data_agent.db_engine import get_engine
from data_agent.agent_messaging import get_message_bus
from datetime import datetime, timedelta


def _get_user_from_request(request: Request):
    """Extract authenticated user from JWT in request cookies."""
    try:
        from chainlit.auth.cookie import get_token_from_cookies
        from chainlit.auth.jwt import decode_jwt
    except ImportError:
        return None
    token = get_token_from_cookies(dict(request.cookies))
    if not token:
        return None
    try:
        return decode_jwt(token)
    except Exception:
        return None


def _is_admin(user) -> bool:
    """Check if user has admin role."""
    if hasattr(user, "metadata") and isinstance(user.metadata, dict):
        return user.metadata.get("role") == "admin"
    return False


async def messaging_stats(request: Request) -> JSONResponse:
    """获取消息统计"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "未授权"}, status_code=401)

    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "数据库不可用"}, status_code=503)

    with engine.connect() as conn:
        result = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN delivered THEN 1 ELSE 0 END) as delivered,
                SUM(CASE WHEN NOT delivered THEN 1 ELSE 0 END) as undelivered,
                COUNT(DISTINCT from_agent) as unique_senders,
                COUNT(DISTINCT to_agent) as unique_receivers
            FROM agent_messages
            WHERE created_at > NOW() - INTERVAL '7 days'
        """).fetchone()

        type_counts = conn.execute("""
            SELECT message_type, COUNT(*) as count
            FROM agent_messages
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY message_type
        """).fetchall()

    return JSONResponse({
        "total": result[0] or 0,
        "delivered": result[1] or 0,
        "undelivered": result[2] or 0,
        "unique_senders": result[3] or 0,
        "unique_receivers": result[4] or 0,
        "by_type": {row[0]: row[1] for row in type_counts},
    })


async def list_messages(request: Request) -> JSONResponse:
    """列出消息（支持过滤）"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "未授权"}, status_code=401)

    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "数据库不可用"}, status_code=503)

    # 查询参数
    from_agent = request.query_params.get("from_agent")
    to_agent = request.query_params.get("to_agent")
    message_type = request.query_params.get("message_type")
    delivered = request.query_params.get("delivered")
    limit = int(request.query_params.get("limit", "100"))

    # 构建查询
    conditions = ["created_at > NOW() - INTERVAL '7 days'"]
    if from_agent:
        conditions.append(f"from_agent = '{from_agent}'")
    if to_agent:
        conditions.append(f"to_agent = '{to_agent}'")
    if message_type:
        conditions.append(f"message_type = '{message_type}'")
    if delivered is not None:
        conditions.append(f"delivered = {delivered.lower() == 'true'}")

    where_clause = " AND ".join(conditions)

    with engine.connect() as conn:
        rows = conn.execute(f"""
            SELECT id, message_id, from_agent, to_agent, message_type,
                   payload, correlation_id, delivered, created_at
            FROM agent_messages
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit}
        """).fetchall()

    messages = []
    for row in rows:
        messages.append({
            "id": row[0],
            "message_id": row[1],
            "from_agent": row[2],
            "to_agent": row[3],
            "message_type": row[4],
            "payload": row[5],
            "correlation_id": row[6],
            "delivered": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
        })

    return JSONResponse({"messages": messages})


async def replay_message(request: Request) -> JSONResponse:
    """重新发送未送达消息"""
    user = _get_user_from_request(request)
    if not user or not _is_admin(user):
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)

    msg_id = request.path_params.get("id")
    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "数据库不可用"}, status_code=503)

    with engine.connect() as conn:
        row = conn.execute(
            "SELECT message_id, from_agent, to_agent, message_type, payload, correlation_id "
            "FROM agent_messages WHERE id = %s AND NOT delivered",
            (msg_id,)
        ).fetchone()

        if not row:
            return JSONResponse({"error": "消息不存在或已送达"}, status_code=404)

    # 重新发布消息
    bus = get_message_bus()
    from data_agent.agent_messaging import AgentMessage
    msg = AgentMessage(
        message_id=row[0], from_agent=row[1], to_agent=row[2],
        message_type=row[3], payload=row[4], correlation_id=row[5]
    )
    await bus.publish(msg)

    return JSONResponse({"status": "success", "message": "消息已重新发送"})


async def cleanup_messages(request: Request) -> JSONResponse:
    """清理旧消息"""
    user = _get_user_from_request(request)
    if not user or not _is_admin(user):
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)

    days = int(request.query_params.get("days", "30"))
    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "数据库不可用"}, status_code=503)

    with engine.connect() as conn:
        result = conn.execute(
            f"DELETE FROM agent_messages WHERE created_at < NOW() - INTERVAL '{days} days' RETURNING id"
        )
        deleted = result.rowcount
        conn.commit()

    return JSONResponse({"status": "success", "deleted": deleted})
