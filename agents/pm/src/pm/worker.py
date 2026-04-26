"""Long-running worker that consumes Jira webhook events from RabbitMQ
and calls the orchestrator."""

import asyncio
import json

import aio_pika
import httpx
import structlog

log = structlog.get_logger()

ORCHESTRATOR_URL = "http://orchestrator.agents-runtime.svc:8000"
RABBITMQ_URL = "amqp://agent:agent@rabbitmq.agents-platform.svc:5672/"
QUEUE = "jira.ticket.created"


async def handle_ticket(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        body = json.loads(message.body)
        jira_ticket_id = body.get("issue", {}).get("key", "")
        github_repo = body.get("github_repo", "")
        if not jira_ticket_id or not github_repo:
            log.warning("pm.worker.skip", body=body)
            return
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ORCHESTRATOR_URL}/workflows",
                json={"jira_ticket_id": jira_ticket_id, "github_repo": github_repo},
                timeout=30,
            )
        log.info("pm.worker.started_workflow", ticket=jira_ticket_id, status=resp.status_code)


async def main() -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE, durable=True)
        await queue.consume(handle_ticket)
        log.info("pm.worker.ready", queue=QUEUE)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
