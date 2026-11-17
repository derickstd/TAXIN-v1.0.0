from django.test import TestCase
from clients.models import Client
from core.models import Branch, Company, User
from credentials.views import CredentialForm


class CredentialBranchAccessTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name='Credential Test Co', slug='credential-test')
        self.branch = Branch.objects.create(company=company, name='Assigned Branch')
        other_branch = Branch.objects.create(company=company, name='Other Branch')
        self.user = User.objects.create_user(
            username='credentialstaff', password='pass1234',
            role='tax_officer', company=company, branch=self.branch,
        )
        self.assigned_client = Client.objects.create(
            full_name='Assigned Client', phone_primary='+256700200001',
            branch=self.branch,
        )
        self.other_client = Client.objects.create(
            full_name='Other Client', phone_primary='+256700200002',
            branch=other_branch,
        )

    def test_credential_form_only_offers_clients_in_assigned_branch(self):
        form = CredentialForm(user=self.user)

        self.assertEqual(list(form.fields['client'].queryset), [self.assigned_client])
        self.assertNotIn(self.other_client, form.fields['client'].queryset)
