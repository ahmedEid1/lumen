from django.urls import path, include
from rest_framework import routers
from . import views


router = routers.DefaultRouter()
router.register('courses', views.CourseViewSet)
app_name = 'courses'

urlpatterns = [
    # ...return a list of all the subjects
    path('subjects/', views.SubjectListView.as_view(), name='subject_list'),
    # ...return the details of a subject
    path('subjects/<pk>', views.SubjectDetailView.as_view(), name='subject_detail'),
    path('', include(router.urls)),

]