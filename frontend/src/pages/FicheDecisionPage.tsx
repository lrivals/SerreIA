import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useDecision } from "@/api/hooks";
import { ErrorBox, Loading } from "@/components/common";
import { FicheDecision } from "@/components/FicheDecision";

export function FicheDecisionPage() {
  const { id } = useParams();
  const { data, error, isLoading } = useDecision(id);
  return (
    <>
      <Link to="/decisions" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Journal des décisions
      </Link>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && <FicheDecision d={data} />}
    </>
  );
}
