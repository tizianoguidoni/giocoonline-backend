import os

file_path = "/Users/tiziano/Desktop/proggetti /gioco/giocoonline-backend/main.py"
with open(file_path, 'r') as f:
    lines = f.readlines()

new_endpoints = """
@api_router.post("/admin/toggle-ban")
async def admin_toggle_ban(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') not in ['super_admin', 'co_admin', 'owner']:
        raise HTTPException(status_code=403, detail="Not authorized")
    username = data.get('username')
    target_user = await db.users.find_one({'username': username})
    if not target_user: raise HTTPException(status_code=404, detail="User not found")
    new_state = not target_user.get('is_banned', False)
    await db.users.update_one({'username': username}, {'$set': {'is_banned': new_state}})
    return {"message": f"User {username} ban state: {new_state}"}

@api_router.post("/admin/set-role")
async def admin_set_role(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') != 'owner' and user.get('role') != 'super_admin':
        raise HTTPException(status_code=403, detail="Only Owners can change roles")
    username = data.get('username')
    new_role = data.get('role')
    await db.users.update_one({'username': username}, {'$set': {'role': new_role}})
    return {"message": f"User {username} role: {new_role}"}

@api_router.post("/admin/give-gold")
async def admin_give_gold(data: dict, user: dict = Depends(get_current_user)):
    if user.get('role') not in ['super_admin', 'owner']:
        raise HTTPException(status_code=403, detail="Not authorized")
    username = data.get('username')
    amount = data.get('amount', 0)
    target_user = await db.users.find_one({'username': username})
    if not target_user: raise HTTPException(status_code=404, detail="User not found")
    await db.characters.update_one({'user_id': target_user['id']}, {'$inc': {'gold': amount}})
    return {"message": f"Gave {amount} gold to {username}"}
"""

# Find line with 'app.include_router(api_router)' and insert before it
insert_idx = -1
for i, line in enumerate(lines):
    if 'app.include_router(api_router)' in line:
        insert_idx = i
        break

if insert_idx != -1:
    lines.insert(insert_idx, new_endpoints)
    with open(file_path, 'w') as f:
        f.writelines(lines)
    print("Successfully added admin endpoints.")
else:
    print("Could not find insertion point.")
