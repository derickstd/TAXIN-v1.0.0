from django.contrib import admin
from .models import ServiceType, JobCard, JobCardLineItem, ClientServiceSubscription, StaffActivityLog
admin.site.register(ServiceType)
admin.site.register(JobCard)
admin.site.register(JobCardLineItem)
admin.site.register(ClientServiceSubscription)
admin.site.register(StaffActivityLog)
