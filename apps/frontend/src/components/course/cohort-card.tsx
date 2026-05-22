"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Courses } from "@/lib/api/endpoints";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

export function CohortCard({ courseId }: { courseId: string }) {
  const t = useT();
  const q = useQuery({
    queryKey: ["course", courseId, "cohort"],
    queryFn: () => Courses.cohort(courseId),
  });
  const hasRows = (q.data?.length ?? 0) > 0;

  return (
    <Card className="surface">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="font-display text-lg leading-tight tracking-tight">
          {t("cohort.title")}
        </CardTitle>
        {hasRows && (
          // Anchor link triggers a real download because the endpoint
          // sets Content-Disposition: attachment. Going through the
          // browser (instead of fetch+blob) keeps the cookie flow and
          // Range support automatic.
          <a
            href={`/api/v1/courses/${courseId}/students.csv`}
            download={`cohort-${courseId}.csv`}
          >
            <Button variant="outline" size="sm">
              <Download className="me-1 h-4 w-4" /> {t("cohort.exportCsv")}
            </Button>
          </a>
        )}
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p className="font-body text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : q.error ? (
          <p className="font-body text-sm text-destructive">
            {(q.error as Error).message ?? t("cohort.loadError")}
          </p>
        ) : !q.data?.length ? (
          <p className="font-body text-sm text-muted-foreground">{t("cohort.empty")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="pb-2 text-start font-medium">{t("cohort.col.student")}</th>
                  <th className="pb-2 text-start font-medium">{t("cohort.col.enrolled")}</th>
                  <th className="pb-2 text-start font-medium">{t("cohort.col.progress")}</th>
                  <th className="pb-2 text-start font-medium">{t("cohort.col.status")}</th>
                </tr>
              </thead>
              <tbody className="font-body">
                {q.data.map((row) => (
                  <tr
                    key={row.user_id}
                    className="border-t border-border align-middle transition-colors duration-[160ms] hover:bg-muted/30"
                  >
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <Avatar className="h-7 w-7 border border-border">
                          <AvatarImage src={row.avatar_url ?? undefined} alt={row.full_name} />
                          <AvatarFallback>
                            {row.full_name.slice(0, 1).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <span className="font-medium">
                          {row.full_name || t("cohort.learnerFallback")}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 font-mono text-xs text-muted-foreground">
                      {formatRelative(row.enrolled_at)}
                    </td>
                    <td className="w-48 py-2">
                      <div className="flex items-center gap-2">
                        <Progress value={row.progress_pct} className="flex-1" />
                        <span className="font-mono text-xs tabular-nums text-muted-foreground">
                          {row.progress_pct.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="py-2">
                      {row.completed_at ? (
                        <Badge>{t("cohort.status.completed")}</Badge>
                      ) : row.progress_pct > 0 ? (
                        <Badge variant="secondary">{t("cohort.status.inProgress")}</Badge>
                      ) : (
                        <Badge variant="muted">{t("cohort.status.notStarted")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
