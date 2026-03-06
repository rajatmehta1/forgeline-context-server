"""
Seed the Neo4j Knowledge Graph with sample data for development/testing.

Usage:
    python scripts/seed_kg.py
"""

from __future__ import annotations

import asyncio
from neo4j import AsyncGraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "forgeline-dev"


async def seed() -> None:
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async with driver.session() as session:
        # Clear existing data
        await session.run("MATCH (n) DETACH DELETE n")
        print("Cleared existing data.")

        # ─── Repository ───
        await session.run("""
            CREATE (r:Repository {
                name: 'acme-saas',
                url: 'https://github.com/acme/acme-saas',
                default_branch: 'main',
                languages: ['typescript', 'python'],
                frameworks: ['express', 'react', 'prisma']
            })
        """)

        # ─── Modules ───
        modules = [
            ("src/controllers/auth.controller.ts", "typescript", "controller", "auth.controller"),
            ("src/controllers/payment.controller.ts", "typescript", "controller", "payment.controller"),
            ("src/services/auth.service.ts", "typescript", "service", "auth.service"),
            ("src/services/payment.service.ts", "typescript", "service", "payment.service"),
            ("src/services/notification.service.ts", "typescript", "service", "notification.service"),
            ("src/repositories/user.repository.ts", "typescript", "repository", "user.repository"),
            ("src/repositories/payment.repository.ts", "typescript", "repository", "payment.repository"),
            ("src/models/user.model.ts", "typescript", "model", "user.model"),
            ("src/models/payment.model.ts", "typescript", "model", "payment.model"),
            ("src/middleware/auth.middleware.ts", "typescript", "middleware", "auth.middleware"),
            ("src/utils/encryption.ts", "typescript", "util", "encryption"),
            ("src/utils/validation.ts", "typescript", "util", "validation"),
        ]
        for fp, lang, layer, mod_name in modules:
            await session.run("""
                CREATE (m:Module {
                    file_path: $fp, language: $lang, layer: $layer,
                    module_name: $mod_name, loc: 150, ai_generated_ratio: 0.3
                })
            """, {"fp": fp, "lang": lang, "layer": layer, "mod_name": mod_name})

        # ─── Functions ───
        functions = [
            ("validateEmail", "validateEmail(email: string): boolean", "src/utils/validation.ts", True, "Validates email format using RFC 5322 regex", "boolean"),
            ("validatePassword", "validatePassword(pwd: string, minLength?: number): boolean", "src/utils/validation.ts", True, "Checks password strength (length, complexity)", "boolean"),
            ("hashPassword", "hashPassword(password: string): Promise<string>", "src/utils/encryption.ts", True, "Hashes password with bcrypt (12 rounds)", "Promise<string>"),
            ("comparePassword", "comparePassword(plain: string, hashed: string): Promise<boolean>", "src/utils/encryption.ts", True, "Constant-time password comparison", "Promise<boolean>"),
            ("encryptField", "encryptField(data: string, key?: string): string", "src/utils/encryption.ts", True, "AES-256 encryption for sensitive fields", "string"),
            ("generateJWT", "generateJWT(userId: string, role: string): string", "src/middleware/auth.middleware.ts", True, "Creates signed JWT with 1h expiry", "string"),
            ("verifyJWT", "verifyJWT(token: string): JWTPayload", "src/middleware/auth.middleware.ts", True, "Verifies and decodes JWT token", "JWTPayload"),
            ("findUserById", "findUserById(id: string): Promise<User | null>", "src/repositories/user.repository.ts", True, "Finds user by ID using Prisma", "Promise<User | null>"),
            ("findUserByEmail", "findUserByEmail(email: string): Promise<User | null>", "src/repositories/user.repository.ts", True, "Finds user by email (unique index)", "Promise<User | null>"),
            ("createUser", "createUser(data: CreateUserDto): Promise<User>", "src/repositories/user.repository.ts", True, "Creates new user record", "Promise<User>"),
            ("processPayment", "processPayment(userId: string, amount: number, token: string): Promise<PaymentResult>", "src/services/payment.service.ts", True, "Processes Stripe payment with validation", "Promise<PaymentResult>"),
        ]

        # Python's True != JS true, need to fix this
        for name, sig, fp, exported, desc, ret_type in functions:
            await session.run("""
                MATCH (m:Module {file_path: $fp})
                CREATE (f:Function {
                    name: $name, signature: $sig, is_exported: true,
                    is_async: $is_async, description: $desc,
                    return_type: $ret_type, cyclomatic_complexity: 5, loc: 25
                })
                CREATE (m)-[:DEFINES]->(f)
            """, {"name": name, "sig": sig, "fp": fp, "desc": desc,
                  "ret_type": ret_type, "is_async": "Promise" in ret_type})

        # ─── Classes ───
        classes = [
            ("UserRepository", "src/repositories/user.repository.ts", "class",
             ["findUserById", "findUserByEmail", "createUser", "updateUser", "deleteUser"]),
            ("PaymentRepository", "src/repositories/payment.repository.ts", "class",
             ["createPayment", "findPaymentById", "findPaymentsByUser"]),
            ("AuthService", "src/services/auth.service.ts", "class",
             ["register", "login", "logout", "refreshToken"]),
            ("PaymentService", "src/services/payment.service.ts", "class",
             ["processPayment", "refundPayment", "getPaymentHistory"]),
            ("User", "src/models/user.model.ts", "interface",
             ["id", "email", "passwordHash", "createdAt", "role"]),
            ("Payment", "src/models/payment.model.ts", "interface",
             ["id", "userId", "amount", "status", "stripeChargeId"]),
        ]
        for name, fp, kind, methods in classes:
            await session.run("""
                MATCH (m:Module {file_path: $fp})
                CREATE (c:Class {
                    name: $name, kind: $kind, is_exported: true,
                    is_abstract: false, description: ''
                })
                CREATE (m)-[:DEFINES]->(c)
            """, {"name": name, "fp": fp, "kind": kind})

        # ─── Sensitive Data Fields ───
        sensitive_fields = [
            ("email", "PII", "src/models/user.model.ts"),
            ("passwordHash", "CREDENTIAL", "src/models/user.model.ts"),
            ("card_token", "PCI", "src/services/payment.service.ts"),
            ("amount", "FINANCIAL", "src/models/payment.model.ts"),
            ("stripeChargeId", "PCI", "src/models/payment.model.ts"),
        ]
        for name, tag, source in sensitive_fields:
            await session.run("""
                CREATE (df:DataField {
                    name: $name, sensitivity_tag: $tag,
                    source_module: $source, encrypted: false, logged: false
                })
            """, {"name": name, "tag": tag, "source": source})

        # ─── Dependencies ───
        deps = [
            ("express", "4.18.2", "npm", 100, True, False, 0, "MIT"),
            ("prisma", "5.14.0", "npm", 95, True, False, 0, "Apache-2.0"),
            ("bcrypt", "5.1.1", "npm", 98, True, False, 0, "MIT"),
            ("jsonwebtoken", "9.0.2", "npm", 97, True, False, 1, "MIT"),
            ("stripe", "14.21.0", "npm", 99, True, False, 0, "MIT"),
            ("zod", "3.23.8", "npm", 96, True, False, 0, "MIT"),
            ("lodash", "4.17.21", "npm", 99, True, False, 0, "MIT"),
            ("axios", "1.7.2", "npm", 90, True, False, 2, "MIT"),
        ]
        for name, ver, reg, trust, approved, phantom, cves, lic in deps:
            await session.run("""
                CREATE (d:Dependency {
                    package_name: $name, version: $ver, registry: $reg,
                    trust_score: $trust, is_approved: $approved,
                    is_phantom: $phantom, cve_count: $cves, license: $lic
                })
            """, {"name": name, "ver": ver, "reg": reg, "trust": trust,
                  "approved": approved, "phantom": phantom, "cves": cves, "lic": lic})

        # ─── Architecture Rules ───
        arch_rules = [
            ("controller", "**/controllers/**", ["service", "middleware", "model", "util"], ["repository"]),
            ("service", "**/services/**", ["repository", "model", "util"], ["controller"]),
            ("repository", "**/repositories/**", ["model", "util"], ["controller", "service"]),
        ]
        for layer, pattern, allowed, forbidden in arch_rules:
            await session.run("""
                MATCH (r:Repository {name: 'acme-saas'})
                CREATE (a:ArchitectureRule {
                    layer_name: $layer, path_pattern: $pattern,
                    allowed_dependencies: $allowed,
                    forbidden_dependencies: $forbidden
                })
                CREATE (r)-[:HAS_ARCHITECTURE]->(a)
            """, {"layer": layer, "pattern": pattern,
                  "allowed": allowed, "forbidden": forbidden})

    await driver.close()
    print("✅ Neo4j seeded with sample data!")
    print("   • 12 modules, 11 functions, 6 classes")
    print("   • 5 sensitive data fields, 8 dependencies")
    print("   • 3 architecture boundary rules")


if __name__ == "__main__":
    asyncio.run(seed())
