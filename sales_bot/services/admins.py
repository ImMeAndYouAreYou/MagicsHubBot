from __future__ import annotations

from sales_bot.db import Database
from sales_bot.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError


class AdminService:
    def __init__(self, database: Database, owner_user_id: int) -> None:
        self.database = database
        self.owner_user_id = owner_user_id

    async def is_admin(self, user_id: int) -> bool:
        if user_id == self.owner_user_id:
            return True

        row = await self.database.fetchone(
            "SELECT user_id FROM admins WHERE user_id = ?",
            (user_id,),
        )
        return row is not None

    async def add_admin(self, user_id: int, added_by: int) -> None:
        if user_id == self.owner_user_id:
            raise AlreadyExistsError("The configured owner already has permanent admin access.")

        if await self.is_admin(user_id):
            raise AlreadyExistsError("That user is already in the admin list.")

        await self.database.execute(
            "INSERT INTO admins (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by),
        )

    async def remove_admin(self, user_id: int) -> None:
        if user_id == self.owner_user_id:
            raise PermissionDeniedError("The configured owner cannot be removed from admin access.")

        if not await self.is_admin(user_id):
            raise NotFoundError("That user is not in the admin list.")

        await self.database.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))

    async def list_admin_ids(self) -> list[int]:
        rows = await self.database.fetchall("SELECT user_id FROM admins ORDER BY added_at ASC")
        admin_ids = [self.owner_user_id]
        admin_ids.extend(int(row["user_id"]) for row in rows)
        return admin_ids
