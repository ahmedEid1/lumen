from django.urls import path
from . import views

urlpatterns = [
    # ...list of the current teacher courses owns(Done)
    path('mine/', views.ManageCourseListView.as_view(), name='manage_course_list'),
    # ...creating a new course (Done)
    path('create/', views.CourseCreateView.as_view(), name='course_create'),
    # ...edit an existing course (Done)
    path('<pk>/edit/', views.CourseUpdateView.as_view(), name='course_edit'),
    # ...delete an existing course (Done)
    path('<pk>/delete/', views.CourseDeleteView.as_view(), name='course_delete'),
    # ...adding, editing and deleting modules of a course (Done)
    path('<pk>/module/', views.CourseModuleUpdateView.as_view(), name='course_module_update'),
    # ...adding a new content (text, image, video, file) to the module (Done)
    path('module/<int:module_id>/content/<model_name>/create/', views.ContentCreateUpdateView.as_view(),
         name='module_content_create'),
    # ...editing a content item of the module (Done)
    path('module/<int:module_id>/content/<model_name>/<id>/', views.ContentCreateUpdateView.as_view(),
         name='module_content_update'),
    # ...deleting a content item from the module (Done)
    path('content/<int:id>/delete', views.ContentDeleteView.as_view(),
         name='module_content_delete'),
    # ...managing the content of a module (Done)
    path('module/<int:module_id>/', views.ModuleContentListView.as_view(),
         name='module_content_list'),
    # ...reordering the modules and contents (no template, called from the drag_drop code)
    path('module/order/', views.ModuleOrderView.as_view(),
         name='module_order'),
    path('content/order/', views.ContentOrderView.as_view(),
         name='content_order'),

    # ...show all courses under the subject (can access from the home page)
    path('subject/<slug:subject>/', views.CourseListView.as_view(), name='course_list_subject'),
    # ...the enroll in page for a course
    path('<slug:slug>/', views.CourseDetailView.as_view(), name='course_detail'),
]
