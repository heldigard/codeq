from __future__ import annotations

from pathlib import Path


def write_fixtures(fixture_dir: Path) -> None:
    (fixture_dir / "calc.py").write_text(
        """\
\"\"\"Calculator helpers.\"\"\"\nimport json\nimport os\n\n\ndef calculate(a: int, b: int) -> int:\n    \"\"\"Add two numbers.\"\"\"\n    return a + b\n\n\nclass Calculator:\n    \"\"\"Simple calculator.\"\"\"\n\n    def total(self, items):\n        return sum(items)\n"""
    )
    (fixture_dir / "main.py").write_text(
        """\
from calc import calculate\n\n\ndef main():\n    value = calculate(1, 2)\n    print(f\"result={value}\")\n\n\nif __name__ == \"__main__":\n    main()\n"""
    )
    (fixture_dir / "debug.py").write_text(
        """\
def greet(name: str) -> None:\n    print(f\"hello {name}\")\n"""
    )


def write_java_fixtures(fixture_dir: Path) -> None:
    (fixture_dir / "Customer.java").write_text(
        """\
package com.example;

public class Customer {
    private Long id;
    private String name;

    public Customer(Long id, String name) {
        this.id = id;
        this.name = name;
    }

    public Long getId() {
        return id;
    }

    public String displayName() {
        return \"Customer: \" + name;
    }
}
"""
    )
    (fixture_dir / "CustomerService.java").write_text(
        """\
package com.example;

public class CustomerService {
    public String greet(Long id, String name) {
        Customer c = new Customer(id, name);
        return c.displayName();
    }
}
"""
    )


def write_typescript_fixtures(fixture_dir: Path) -> None:
    (fixture_dir / "version-check.service.ts").write_text(
        """\
export class VersionCheckService {
  private version: string;

  constructor(version: string) {
    this.version = version;
  }

  public getCurrent(): string {
    return this.version;
  }

  public isStable(): boolean {
    return this.version.includes(\"stable\");
  }
}
"""
    )
    (fixture_dir / "caller.ts").write_text(
        """\
import { VersionCheckService } from \"./version-check.service\";

export function reportVersion(v: string): string {
  const svc = new VersionCheckService(v);
  return svc.getCurrent();
}
"""
    )
    (fixture_dir / "angular-component.service.ts").write_text(
        """\
import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ChatbotService {
  private readonly config = inject<RuntimeConfig>(RuntimeConfig);

  protected onMessagesScroll(event: Event): void {
    console.log(event);
  }

  protected async submitMessage(): Promise<void> {
    await Promise.resolve();
  }

  protected handleStreamFailure(error: unknown, msg: string): void {
    console.error(msg, error);
  }
}
"""
    )
    (fixture_dir / "caller-of-chatbot.ts").write_text(
        """\
import { ChatbotService } from './angular-component.service';

export function bindScroll(svc: ChatbotService, ev: Event): void {
  svc.onMessagesScroll(ev);
  svc.handleStreamFailure(new Error('boom'), 'failed');
  return svc.submitMessage();
}
"""
    )
    (fixture_dir / "advanced-generic.service.ts").write_text(
        """\
import { Injectable, OnInit, inject } from '@angular/core';

type RuntimeKey = 'primary' | 'fallback';
type RuntimeState = Record<RuntimeKey, string>;

class BaseService<TState> {
  protected adapter = {
    pick<TKey extends keyof TState>(key: TKey): TState[TKey] {
      return {} as TState[TKey];
    }
  };
}

@Injectable({ providedIn: 'root' })
export abstract class AdvancedGenericService<TItem extends RuntimeState>
  extends BaseService<TItem>
  implements OnInit {
  public ngOnInit(): void {
    this.loadFor('primary');
  }

  private readonly config = inject<RuntimeState>(Object);

  protected override async loadFor<TKey extends keyof TItem>(
    key: TKey,
  ): Promise<TItem[TKey]> {
    return this.selectOne(key);
  }

  protected selectOne<TKey extends keyof TItem>(key: TKey): TItem[TKey] {
    return this.adapter.pick(key);
  }

  protected handleFailure(error: unknown): void {
    console.error(error);
  }
}
"""
    )
