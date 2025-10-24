import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

interface LoginPageProps {
  onLogin: () => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username && password) {
      onLogin();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-slate-100 flex items-center justify-center p-4">
      <Card className="w-full max-w-md shadow-xl border-slate-200">
        <CardContent className="pt-12 pb-8 px-8">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl mb-4 kb-burgundy">
              <span className="text-white text-3xl tracking-tight">KB</span>
            </div>
            <h1 className="text-2xl text-slate-900 mb-2">Kiwoom-Bank</h1>
            <p className="text-base text-slate-600">
              기업 신용 위험 모니터링 AI 에이전트
            </p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="username">사용자 아이디</Label>
              <Input
                id="username"
                type="text"
                placeholder="사용자 아이디를 입력하세요"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="bg-white border-slate-300"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">비밀번호</Label>
              <Input
                id="password"
                type="password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="bg-white border-slate-300"
              />
            </div>

            <Button
              type="submit"
              variant="default"
              className="w-full font-semibold py-6"
            >
              로그인
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
