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

export function CohortCard({ courseId }: { courseId: string }) {
  const q = useQuery({
    queryKey: ["course", courseId, "cohort"],
    queryFn: () => Courses.cohort(courseId),
  });
  const hasRows = (q.data?.length ?? 0) > 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Students</CardTitle>
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
              <Download className="mr-1 h-4 w-4" /> Export CSV
            </Button>
          </a>
        )}
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : q.error ? (
          <p className="text-sm text-destructive">
            {(q.error as Error).message ?? "Could not load cohort"}
          </p>
        ) : !q.data?.length ? (
          <p className="text-sm text-muted-foreground">No enrolments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="pb-2">Student</th>
                  <th className="pb-2">Enrolled</th>
                  <th className="pb-2">Progress</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {q.data.map((row) => (
                  <tr key={row.user_id} className="border-t align-middle">
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <Avatar className="h-7 w-7">
                          <AvatarImage src={row.avatar_url ?? undefined} alt={row.full_name} />
                          <AvatarFallback>{row.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
                        </Avatar>
                        <span className="font-medium">{row.full_name || "Learner"}</span>
                      </div>
                    </td>
                    <td className="py-2 text-muted-foreground">{formatRelative(row.enrolled_at)}</td>
                    <td className="w-48 py-2">
                      <div className="flex items-center gap-2">
                        <Progress value={row.progress_pct} className="flex-1" />
                        <span className="tabular-nums text-xs text-muted-foreground">
                          {row.progress_pct.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="py-2">
                      {row.completed_at ? (
                        <Badge>completed</Badge>
                      ) : row.progress_pct > 0 ? (
                        <Badge variant="secondary">in progress</Badge>
                      ) : (
                        <Badge variant="muted">not started</Badge>
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
