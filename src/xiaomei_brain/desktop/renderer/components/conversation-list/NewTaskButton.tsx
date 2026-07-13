import { useTranslation } from "react-i18next";
import { Button } from "../ui";

interface NewTaskButtonProps {
  onClick: () => void;
}

export function NewTaskButton({ onClick }: NewTaskButtonProps) {
  const { t } = useTranslation();
  return (
    <Button variant="secondary" size="md" icon="plus" className="new-task-button" onClick={onClick}>
      {t("sidebar.newTask")}
    </Button>
  );
}
