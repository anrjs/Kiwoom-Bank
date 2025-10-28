import { ArrowLeft, Bell, TrendingDown, TrendingUp, AlertCircle } from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";

export interface Notification {
  id: number;
  type: "down" | "warning" | "up";
  companyName: string;
  title: string;
  ratingChange?: string;
  newsKeywords: string;
  timestamp: string;
  isRead: boolean;
}

interface NotificationInboxProps {
  notifications: Notification[];
  onBack: () => void;
  onSelectNotification: (id: number) => void;
}

export function NotificationInbox({
  notifications,
  onBack,
  onSelectNotification,
}: NotificationInboxProps) {
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "down":
        return <TrendingDown className="w-5 h-5 text-red-600" />;
      case "warning":
        return <AlertCircle className="w-5 h-5 text-yellow-600" />;
      case "up":
        return <TrendingUp className="w-5 h-5 text-green-600" />;
      default:
        return <Bell className="w-5 h-5" />;
    }
  };

  const getTypeBadge = (type: string) => {
    switch (type) {
      case "down":
        return (
          <Badge className="bg-red-100 text-red-700 border-red-200">
            등급 하락
          </Badge>
        );
      case "warning":
        return (
          <Badge className="bg-yellow-100 text-yellow-700 border-yellow-200">
            하락 위험
          </Badge>
        );
      case "up":
        return (
          <Badge className="bg-green-100 text-green-700 border-green-200">
            등급 상승
          </Badge>
        );
      default:
        return null;
    }
  };

  const getCardStyle = (type: string, isRead: boolean) => {
    const baseStyle = "cursor-pointer transition-all hover:shadow-lg ";
    const readStyle = isRead ? "bg-slate-50 opacity-80 " : "bg-white ";
    
    if (!isRead) {
      switch (type) {
        case "down":
          return baseStyle + "border-l-4 border-l-red-500 " + readStyle;
        case "warning":
          return baseStyle + "border-l-4 border-l-yellow-500 " + readStyle;
        case "up":
          return baseStyle + "border-l-4 border-l-green-500 " + readStyle;
      }
    }
    
    return baseStyle + readStyle + "border-l-4 border-l-slate-300";
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-900 flex items-center justify-center">
              <span className="text-white tracking-tight">ACI</span>
            </div>
            <span className="text-slate-900">AI Credit Insight</span>
          </div>
          <Button onClick={onBack} variant="ghost" className="text-slate-600">
            <ArrowLeft className="w-4 h-4 mr-2" />
            돌아가기
          </Button>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Bell className="w-8 h-8 text-blue-900" />
            <h1 className="text-slate-900">알림함</h1>
          </div>
          <p className="text-slate-600">
            신용등급 변동 및 위험 알림 내역을 확인하세요
          </p>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <Card className="p-4">
            <div className="text-slate-600 mb-1">전체 알림</div>
            <div className="text-slate-900">{notifications.length}개</div>
          </Card>
          <Card className="p-4 bg-blue-50 border-blue-200">
            <div className="text-blue-700 mb-1">읽지 않음</div>
            <div className="text-blue-900">
              {notifications.filter((n) => !n.isRead).length}개
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-slate-600 mb-1">읽음</div>
            <div className="text-slate-900">
              {notifications.filter((n) => n.isRead).length}개
            </div>
          </Card>
        </div>

        {/* Notifications List */}
        <div className="space-y-4">
          {notifications.map((notification, index) => (
            <Card
              key={notification.id}
              className={getCardStyle(notification.type, notification.isRead)}
              onClick={() => onSelectNotification(notification.id)}
            >
              <div className="p-5">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-10 h-10 rounded-full bg-slate-100 text-slate-700">
                      {notifications.length - index}
                    </div>
                    {getTypeIcon(notification.type)}
                    {getTypeBadge(notification.type)}
                    {notification.isRead ? (
                      <Badge variant="outline" className="bg-slate-100 text-slate-600">
                        읽음
                      </Badge>
                    ) : (
                      <Badge className="bg-blue-600 text-white animate-pulse">
                        읽지 않음
                      </Badge>
                    )}
                  </div>
                  <span className="text-slate-500">{notification.timestamp}</span>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-900">
                      {notification.companyName}
                    </span>
                    {notification.ratingChange && (
                      <span className="text-slate-600 bg-slate-100 px-3 py-1 rounded-lg">
                        {notification.ratingChange}
                      </span>
                    )}
                  </div>

                  <p className={notification.isRead ? "text-slate-600" : "text-slate-900"}>
                    {notification.title}
                  </p>

                  <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
                    <span className="text-slate-500">키워드:</span>
                    <span className="text-slate-700">{notification.newsKeywords}</span>
                  </div>
                </div>
              </div>
            </Card>
          ))}

          {notifications.length === 0 && (
            <Card className="p-12 text-center">
              <Bell className="w-12 h-12 text-slate-300 mx-auto mb-4" />
              <p className="text-slate-500">알림이 없습니다</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
