import type { MessageKey } from "./en";

/** Arabic UI translations. Every key in en.ts must exist here too —
 *  enforced by ``tests/i18n-parity.test.ts``. Arabic conventions:
 *
 *  * Arabic numerals (٠١٢٣٤٥٦٧٨٩) only when culturally expected;
 *    most software contexts use Western digits for prices / counts.
 *    We use Western digits throughout for app counts.
 *  * Punctuation: Arabic question mark is ؟ (U+061F), comma is ، (U+060C).
 *  * Direction: handled at the layout level via ``dir="rtl"`` on <html>;
 *    individual strings do not embed BiDi marks.
 */
export const ar: Record<MessageKey, string> = {
  // Navigation / header
  "nav.catalog": "الدورات",
  "nav.dashboard": "لوحة التحكم",
  "nav.studio": "الاستوديو",
  "nav.admin": "الإدارة",
  "nav.signIn": "تسجيل الدخول",
  "nav.signUp": "إنشاء حساب",
  "nav.profile": "الملف الشخصي",
  "nav.signOut": "تسجيل الخروج",
  "nav.search.placeholder": "ابحث عن دورة…",
  "nav.notifications.aria": "الإشعارات",

  // Catalog
  "catalog.title": "الدورات",
  "catalog.filters.subject": "الموضوع",
  "catalog.filters.difficulty": "المستوى",
  "catalog.filters.tag": "الوسم",
  "catalog.filters.all": "الكل",
  "catalog.empty": "لا توجد دورات تطابق هذه المرشحات.",
  "catalog.featuredBadge": "مميّزة",

  // Course detail
  "course.enroll": "التسجيل",
  "course.continue": "متابعة التعلم",
  "course.start": "ابدأ التعلم",
  "course.bookmark": "إضافة إلى المفضّلة",
  "course.bookmarked": "في المفضّلة",
  "course.syllabus": "المنهج",
  "course.reviews": "المراجعات",
  "course.modules": "الوحدات",
  "course.students": "الطلاب",
  "course.rating": "التقييم",
  "course.progress": "التقدّم",
  "course.signInToEnroll": "سجّل الدخول للتسجيل",
  "course.discussionForum": "منتدى النقاش",
  "course.whatYoullLearn": "ماذا ستتعلم",
  "course.lessonsCount": "{count} درس",
  "course.lastUpdated": "آخر تحديث {date}",

  // Lesson player / progress
  "player.previous": "السابق",
  "player.next": "التالي",
  "player.markComplete": "تم الإنجاز — التالي",
  "player.completed": "تم",
  "player.freePreview": "معاينة مجانية",

  // Auth
  "auth.login.title": "تسجيل الدخول",
  "auth.login.email": "البريد الإلكتروني",
  "auth.login.password": "كلمة المرور",
  "auth.login.submit": "دخول",
  "auth.login.noAccount": "ليس لديك حساب؟",
  "auth.register.title": "إنشاء حساب",
  "auth.register.fullName": "الاسم الكامل",
  "auth.register.submit": "إنشاء حساب",
  "auth.register.haveAccount": "لديك حساب بالفعل؟",
  "auth.forgotPassword": "نسيت كلمة المرور؟",

  // Dashboard — قاعة سجلات الكاتب
  "dashboard.cartouche": "قاعة سجلاتك",
  "dashboard.welcome": "أهلًا بعودتك يا {name}",
  "dashboard.subtitle": "تابع من حيث تركت قلمك.",
  "dashboard.inProgress": "قيد التقدّم",
  "dashboard.bookmarks": "العلامات المرجعية",
  "dashboard.completed": "مكتمل",
  "dashboard.empty.enrollments": "لم تسجّل في أي دورة بعد.",
  "dashboard.empty.browse": "تصفّح الدورات",
  "dashboard.empty.completed": "لا اكتمالات بعد — كل كاتب يبدأ بورق فارغ.",
  "dashboard.percentComplete": "{pct}٪ مكتمل",
  "dashboard.continue": "متابعة",
  "dashboard.certificate": "الشهادة",

  // Generic
  "common.loading": "جارٍ التحميل…",
  "common.save": "حفظ",
  "common.saving": "جارٍ الحفظ…",
  "common.cancel": "إلغاء",
  "common.delete": "حذف",
  "common.edit": "تعديل",
  "common.notFound": "غير موجود",
  "common.tryAgain": "حاول مرة أخرى",
  "common.language": "اللغة",
};
