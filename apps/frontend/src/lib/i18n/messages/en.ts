/** English UI messages. Source of truth — every key here must exist in
 *  every other locale file. ``check-locales.test.ts`` enforces parity.
 */
export const en = {
  // Navigation / header
  "nav.catalog": "Catalog",
  "nav.dashboard": "Dashboard",
  "nav.studio": "Studio",
  "nav.admin": "Admin",
  "nav.signIn": "Sign in",
  "nav.signUp": "Sign up",
  "nav.profile": "Profile",
  "nav.signOut": "Sign out",
  "nav.search.placeholder": "Search courses…",
  "nav.notifications.aria": "Notifications",

  // Catalog
  "catalog.title": "Courses",
  "catalog.filters.subject": "Subject",
  "catalog.filters.difficulty": "Difficulty",
  "catalog.filters.tag": "Tag",
  "catalog.filters.all": "All",
  "catalog.empty": "No courses match those filters.",
  "catalog.featuredBadge": "Featured",

  // Course detail
  "course.enroll": "Enroll",
  "course.continue": "Continue learning",
  "course.start": "Start learning",
  "course.bookmark": "Bookmark",
  "course.bookmarked": "Bookmarked",
  "course.syllabus": "Syllabus",
  "course.reviews": "Reviews",
  "course.modules": "Modules",
  "course.students": "Students",
  "course.rating": "Rating",
  "course.progress": "Progress",
  "course.signInToEnroll": "Sign in to enroll",
  "course.discussionForum": "Discussion forum",
  "course.whatYoullLearn": "What you'll learn",
  "course.lessonsCount": "{count} lessons",
  "course.lastUpdated": "last updated {date}",

  // Lesson player / progress
  "player.previous": "Previous",
  "player.next": "Next",
  "player.markComplete": "Mark complete & continue",
  "player.completed": "Completed",
  "player.freePreview": "free preview",

  // Auth
  "auth.login.title": "Sign in",
  "auth.login.email": "Email",
  "auth.login.password": "Password",
  "auth.login.submit": "Sign in",
  "auth.login.noAccount": "Don't have an account?",
  "auth.register.title": "Create account",
  "auth.register.fullName": "Full name",
  "auth.register.submit": "Create account",
  "auth.register.haveAccount": "Already have an account?",
  "auth.forgotPassword": "Forgot password?",

  // Generic
  "common.loading": "Loading…",
  "common.save": "Save",
  "common.saving": "Saving…",
  "common.cancel": "Cancel",
  "common.delete": "Delete",
  "common.edit": "Edit",
  "common.notFound": "Not found",
  "common.tryAgain": "Try again",
  "common.language": "Language",
} as const;

export type MessageKey = keyof typeof en;
