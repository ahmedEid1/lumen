from django.views.decorators.cache import cache_page
from django.urls import path
from . import views

urlpatterns = [
    # ...creating a new student account
    path('register/', views.StudentRegistrationView.as_view(), name='student_registration'),
    # ...add the student to the course list of students
    path('enroll-course/', views.StudentEnrollCourseView.as_view(), name='student_enroll_course'),
    # ...list of all the courses the user is enrolled in
    path('courses/', views.StudentCourseListView.as_view(), name='student_course_list'),
    # ...course detail page + course chat room
    path('coursjes/<pk>/', views.StudentCourseDetailView.as_view(), name='student_course_detail'),
    # ...showing the contents of a course module
    path('courses/<pk>/<module_id>', views.StudentCourseDetailView.as_view(), name='student_course_detail_module'),
    # ...using caching to cache a view
    # path('courses/<pk>/', cache_page(60 * 15)(views.StudentCourseDetailView.as_view()), name='student_course_detail'),
    # path('courses/<pk>/<module_id>', cache_page(60 * 15)(views.StudentCourseDetailView.as_view()),
    #      name='student_course_detail_module'),

]