from django.contrib.auth import get_user_model
from django.test import TestCase

from projects.models import (
    AgentRun,
    AgentApprovalRequest,
    Project,
    Task,
)
from projects.ai.agent_tools import (
    get_agent_tool_approval,
    consume_agent_tool_approval,
)


class AgentApprovalSecurityTests(TestCase):

    def test_upload_approval_security(self):
        user = get_user_model().objects.create_user(
            username="approval_test_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Approval Security Test",
        )

        task = Task.objects.create(
            project=project,
            title="Test browser upload",
        )

        run = AgentRun.objects.create(
            project=project,
            task=task,
            user=user,
        )

        approved_args = {
            "ref": "e11",
            "workspace_path": "report.pdf",
        }

        approval = AgentApprovalRequest.objects.create(
            run=run,
            continuation_run=run,
            action_type="browser_upload",
            title="Approve test upload",
            description="Test upload authorization",
            tool_name="browser_upload",
            tool_arguments=approved_args,
            status=AgentApprovalRequest.Status.APPROVED,
        )

        matched = get_agent_tool_approval(
            run=run,
            tool_name="browser_upload",
            arguments=approved_args,
        )

        self.assertIsNotNone(matched)
        self.assertEqual(matched.pk, approval.pk)
        print("PASS: Exact approval matched")

        modified = get_agent_tool_approval(
            run=run,
            tool_name="browser_upload",
            arguments={
                "ref": "e11",
                "workspace_path": "passwords.txt",
            },
        )

        self.assertIsNone(modified)
        print("PASS: Modified arguments rejected")

        consume_agent_tool_approval(approval=approval)

        approval.refresh_from_db()
        self.assertIsNotNone(approval.consumed_at)
        print("PASS: Approval consumed")

        with self.assertRaises(ValueError):
            consume_agent_tool_approval(approval=approval)

        print("PASS: Approval cannot be consumed twice")

        reused = get_agent_tool_approval(
            run=run,
            tool_name="browser_upload",
            arguments=approved_args,
        )

        self.assertIsNone(reused)
        print("PASS: Consumed approval cannot be reused")
