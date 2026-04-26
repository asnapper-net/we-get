# Incident Response Runbook

## DevOps Agent Escalation

When the DevOps Agent posts to `#agent-incidents`, check:

1. ArgoCD `Application` CR sync status: `kubectl get application -n argocd`
2. Pod logs: `kubectl logs -n agents-runtime -l app=orchestrator --tail=100`
3. Langfuse trace for the workflow run ID (visible in the Slack message)

## Break-Glass: Disable Agent Approvals

Add the `override-agent-review` label to a PR (requires senior engineer team membership).
The label dismisses the agent's review and opens the PR for direct human merge.

## Rollback a Staging Deployment

Patch the ArgoCD `Application` CR:

```bash
kubectl patch application <app-name> -n argocd \
  --type=merge \
  -p '{"spec":{"source":{"targetRevision":"<previous-sha>"}}}'
```

The DevOps Agent monitors sync status and reports back to `#agent-incidents`.
