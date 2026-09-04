import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { getTelegram } from "../lib/telegram";

export function TelegramBackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  const show = location.pathname !== "/";

  useEffect(() => {
    const button = getTelegram()?.BackButton;
    if (!button) {
      return;
    }
    const onClick = () => navigate(-1);
    if (show) {
      button.show();
      button.onClick(onClick);
    } else {
      button.hide();
    }
    return () => {
      button.offClick(onClick);
      button.hide();
    };
  }, [navigate, show]);

  return null;
}
